"""Sensor.Community (Luftdaten) SDS011 citizen sensors in Ljubljana."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..schema import MEASUREMENT
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "sensor_community"
FILE = Path("01_meritve") / "sensor_community_lj_urno_2023_2026.csv"

USECOLS = [
    "time_utc",
    "sensor_id",
    "lat",
    "lon",
    "pm10",
    "pm25",
    "flag",
]


def read(task: Task):
    path = task.root / FILE
    if not path.exists():
        log.warning("missing input %s", path)
        return
    df = pd.read_csv(path, usecols=lambda c: c in USECOLS, dtype={"flag": "string"}, low_memory=False)
    if df.empty:
        return

    df["time"] = parse_utc(df["time_utc"])
    df["station_id"] = df["sensor_id"].map(lambda v: task.registry.by_sensor("sensor_community", v))
    df["station_source_code"] = df["sensor_id"].astype("string")
    df["station_name"] = df["station_id"].map(
        lambda sid: getattr(task.registry.get(sid), "name", None)
    )
    df["altitude_m"] = None
    df["altitude_source"] = None
    flagged = df["flag"].notna() & (df["flag"].astype("string").str.len() > 0)
    df["quality"] = flagged.map({True: "sensor_fault", False: "ok"})
    df["quality_detail"] = df["flag"].where(flagged)

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
        value_vars=["pm10", "pm25"],
        var_name="_pollutant",
        value_name="value",
    )
    long["pollutant"] = long["_pollutant"]
    long = long.drop(columns="_pollutant")

    yield add_provenance(long, source=NAME, value_type=MEASUREMENT, aggregation="hour")


SPEC = SourceSpec(
    name=NAME,
    value_type=MEASUREMENT,
    priority=5,
    description="Sensor.Community SDS011 citizen sensors (9 outdoor devices, winters 2023/24-2026/27).",
    reader=read,
)
