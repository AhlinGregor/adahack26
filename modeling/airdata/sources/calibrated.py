"""Calibrated citizen-sensor values (the data package's own *estimate* product).

The values are the package's calibrated PM2.5/PM10 for the 12 citizen devices,
calibrated against the nearest ARSO station.  They are marked ``estimate`` so
they are never mistaken for measurements.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..schema import ESTIMATE
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "sensor_calibrated"
FILE = Path("01_meritve") / "senzorji_umerjeno_urno.csv.gz"

USECOLS = [
    "time_utc",
    "source",
    "sensor_id",
    "lat",
    "lon",
    "pm25_cal",
    "pm10_cal",
    "cal_station",
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
    df["station_id"] = [
        task.registry.by_sensor(str(src), sid)
        for src, sid in zip(df["source"].astype(str), df["sensor_id"])
    ]
    df["station_source_code"] = df["sensor_id"].astype("string")
    df["station_name"] = df["station_id"].map(
        lambda sid: getattr(task.registry.get(sid), "name", None)
    )
    df["altitude_m"] = None
    df["altitude_source"] = None
    df["quality"] = "ok"
    df["quality_detail"] = "calibrated_to=" + df["cal_station"].astype("string")

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
        value_vars=["pm25_cal", "pm10_cal"],
        var_name="_pollutant",
        value_name="value",
    )
    long["pollutant"] = long["_pollutant"].str.replace("_cal", "", regex=False)
    long = long.drop(columns="_pollutant")

    yield add_provenance(long, source=NAME, value_type=ESTIMATE, aggregation="hour")


SPEC = SourceSpec(
    name=NAME,
    value_type=ESTIMATE,
    priority=None,
    description="Calibrated citizen-sensor PM values (estimate, calibrated to nearest ARSO station).",
    reader=read,
)
