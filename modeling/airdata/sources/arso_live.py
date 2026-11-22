"""ARSO live XML capture: all pollutants at 25 Slovenian stations (Nov 2026)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import MEASUREMENT, canonical_pollutant
from .base import (
    SourceSpec,
    Task,
    add_provenance,
    fill_missing_coords,
    parse_below_detection,
    parse_fixed_utc_plus_1,
)

log = logging.getLogger(__name__)

NAME = "arso_live"
FILE = Path("05_zadnji_dnevi") / "arso_live_urno_vse_postaje.csv"

#: ARSO XML pollutant tag -> (canonical name, factor to µg/m³).
#: CO is published in mg/m³ by ARSO and converted here to keep one unit.
POLLUTANT_COLUMNS: dict[str, tuple[str, float]] = {
    "so2": ("so2", 1.0),
    "co": ("co", 1000.0),
    "o3": ("o3", 1.0),
    "no2": ("no2", 1.0),
    "nox": ("nox", 1.0),
    "pm10": ("pm10", 1.0),
    "pm25": ("pm25", 1.0),
    "benzen": ("benzene", 1.0),
}


def read(task: Task):
    path = task.root / FILE
    if not path.exists():
        log.warning("missing input %s", path)
        return
    df = pd.read_csv(path, dtype=str)
    if df.empty:
        return

    df["time"] = parse_fixed_utc_plus_1(df["time_from_local"])
    df = df.rename(
        columns={
            "station_code": "station_source_code",
            "station_name": "station_name",
            "alt_m": "altitude_m",
        }
    )
    df["station_id"] = df["station_source_code"].map(task.registry.by_arso)
    df["lat"] = pd.to_numeric(df.get("lat"), errors="coerce")
    df["lon"] = pd.to_numeric(df.get("lon"), errors="coerce")
    df["altitude_m"] = pd.to_numeric(df.get("altitude_m"), errors="coerce")
    df["altitude_source"] = np.where(df["altitude_m"].notna(), "station_metadata", None)
    df = fill_missing_coords(df, task.registry)

    id_cols = [
        "time",
        "station_id",
        "station_name",
        "station_source_code",
        "lat",
        "lon",
        "altitude_m",
        "altitude_source",
    ]
    parts = []
    for column, (pollutant, factor) in POLLUTANT_COLUMNS.items():
        if column not in df.columns:
            continue
        values, below = parse_below_detection(df[column])
        part = df.loc[:, id_cols].copy()
        part["pollutant"] = canonical_pollutant(pollutant)
        part["value"] = values.to_numpy() * factor
        part["quality"] = np.where(below, "below_detection", "ok")
        part["quality_detail"] = np.where(below, "value below detection limit; stored as limit/2", None)
        parts.append(part)
    if not parts:
        return
    yield add_provenance(
        pd.concat(parts, ignore_index=True),
        source=NAME,
        value_type=MEASUREMENT,
        aggregation="hour",
    )


SPEC = SourceSpec(
    name=NAME,
    value_type=MEASUREMENT,
    priority=2,
    description="ARSO live hourly feed (13-21 Nov 2026), 25 stations, SO2/CO/O3/NO2/NOx/PM10/PM2.5/benzene.",
    reader=read,
)
