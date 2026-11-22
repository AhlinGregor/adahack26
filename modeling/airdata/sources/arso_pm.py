"""ARSO hourly PM10 / PM2.5 at the three Ljubljana stations (2016-2026)."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..schema import MEASUREMENT
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

FILES = (
    Path("01_meritve") / "arso_lj_pm_urno_2016_2026.csv.gz",
    Path("01_meritve") / "arso_lj_pm_urno_2026_11_dopolnitev.csv",
)
USECOLS = [
    "time_utc",
    "station_code",
    "station_name",
    "lat",
    "lon",
    "alt_m",
    "pm10",
    "pm25",
]

NAME = "arso_pm"


def _load(root: Path) -> pd.DataFrame:
    frames = []
    for rel in FILES:
        path = root / rel
        if not path.exists():
            log.warning("missing input %s", path)
            continue
        chunk = pd.read_csv(path, usecols=lambda c: c in USECOLS)
        frames.append(chunk)
    if not frames:
        return pd.DataFrame(columns=USECOLS)
    df = pd.concat(frames, ignore_index=True)
    df["time_utc"] = parse_utc(df["time_utc"])
    # The continuation file repeats the boundary timestamp of the main file.
    df = df.drop_duplicates(subset=["station_code", "time_utc"], keep="last")
    return df


def read(task: Task):
    df = _load(task.root)
    if df.empty:
        return
    df = df.rename(
        columns={
            "time_utc": "time",
            "station_code": "station_source_code",
            "alt_m": "altitude_m",
        }
    )
    df["station_id"] = df["station_source_code"].map(task.registry.by_arso)
    df["altitude_source"] = "station_metadata"
    df["quality"] = "ok"
    df["quality_detail"] = pd.NA

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

    yield add_provenance(
        long,
        source=NAME,
        value_type=MEASUREMENT,
        aggregation="hour",
    )


SPEC = SourceSpec(
    name=NAME,
    value_type=MEASUREMENT,
    priority=1,
    description="Official ARSO hourly PM10/PM2.5, LJ Bežigrad, Celovška, Vič (2016-2026).",
    reader=read,
)
