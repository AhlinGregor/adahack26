"""PurpleAir citizen sensors: three outdoor devices in the Ljubljana basin."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import MEASUREMENT, canonical_pollutant_series
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "purpleair"
FILE = Path("01_meritve") / "purpleair_lj_urno.csv"

USECOLS = [
    "time_utc",
    "sensor_index",
    "name",
    "lat",
    "lon",
    "alt_m",
    "pm1_atm",
    "pm25_atm",
    "pm25_atm_a",
    "pm25_atm_b",
    "pm10_atm",
]


def read(task: Task):
    path = task.root / FILE
    if not path.exists():
        log.warning("missing input %s", path)
        return
    df = pd.read_csv(path, usecols=lambda c: c in USECOLS, low_memory=False)
    if df.empty:
        return

    df["time"] = parse_utc(df["time_utc"])
    df["station_id"] = df["sensor_index"].map(lambda v: task.registry.by_sensor("purpleair", v))
    df["station_source_code"] = df["sensor_index"].astype("string")
    df["station_name"] = df["name"]
    df["altitude_m"] = pd.to_numeric(df.get("alt_m"), errors="coerce")
    df["altitude_source"] = np.where(df["altitude_m"].notna(), "station_metadata", None)

    # The two independent PM2.5 channels disagreeing strongly is a useful
    # data-quality signal (dirty or failed sensor).
    denom = np.maximum(df["pm25_atm"].abs(), 1.0)
    spread = (df["pm25_atm_a"] - df["pm25_atm_b"]).abs() / denom
    df["quality"] = np.where(spread > 0.5, "channel_disagreement", "ok")
    df["quality_detail"] = np.where(
        spread > 0.5,
        "PM2.5 channels A and B differ by more than 50%",
        None,
    )

    id_cols = [
        "time",
        "station_id",
        "station_name",
        "station_source_code",
        "lat",
        "lon",
        "altitude_m",
        "altitude_source",
        "quality",
        "quality_detail",
    ]
    long = df.melt(
        id_vars=id_cols,
        value_vars=["pm1_atm", "pm25_atm", "pm10_atm"],
        var_name="_pollutant",
        value_name="value",
    )
    long["pollutant"] = canonical_pollutant_series(long["_pollutant"].str.replace("_atm", "", regex=False))
    long = long.drop(columns="_pollutant")

    yield add_provenance(long, source=NAME, value_type=MEASUREMENT, aggregation="hour")


SPEC = SourceSpec(
    name=NAME,
    value_type=MEASUREMENT,
    priority=4,
    description="PurpleAir PA-II citizen sensors (3 devices, 2021-2026, factory ATM conversion).",
    reader=read,
)
