"""CAMS Europe 0.1° hourly values (archive and 4-day forecast) at 8 basin points."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..schema import MODEL
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "cams"
FORECAST_NAME = "cams_forecast"

FILES = {
    NAME: Path("02_modeli") / "cams_openmeteo_urno_2016_2026.csv.gz",
    FORECAST_NAME: Path("02_modeli") / "cams_openmeteo_napoved_20261113.csv",
}

POLLUTANT_COLUMNS = [
    "pm10",
    "pm2_5",
    "nitrogen_dioxide",
    "ozone",
    "sulphur_dioxide",
    "carbon_monoxide",
    "dust",
]

USECOLS = [
    "time_utc",
    "issued_utc",
    "point_id",
    "point_name",
    "model_lat",
    "model_lon",
    "model_elev_m",
] + POLLUTANT_COLUMNS


def _prepare(chunk: pd.DataFrame, task: Task) -> pd.DataFrame:
    chunk = chunk.copy()
    chunk["time"] = parse_utc(chunk["time_utc"])
    chunk["issued_utc"] = parse_utc(chunk.get("issued_utc"))
    chunk["station_id"] = chunk["point_id"]
    chunk["station_source_code"] = chunk["point_id"]
    chunk["station_name"] = chunk.get("point_name")
    # For model rows lat/lon/altitude describe the model cell the value
    # actually applies to, not the requested station.
    chunk["lat"] = pd.to_numeric(chunk["model_lat"], errors="coerce")
    chunk["lon"] = pd.to_numeric(chunk["model_lon"], errors="coerce")
    chunk["altitude_m"] = pd.to_numeric(chunk["model_elev_m"], errors="coerce")
    chunk["altitude_source"] = "cams_cell"
    chunk["quality"] = "ok"
    chunk["quality_detail"] = "CAMS Europe 0.1 deg cell"

    id_cols = [
        "time",
        "issued_utc",
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
    return chunk.melt(
        id_vars=id_cols,
        value_vars=POLLUTANT_COLUMNS,
        var_name="_pollutant",
        value_name="value",
    )


def _iter(path: Path, task: Task, forecast: bool):
    if not path.exists():
        log.warning("missing input %s", path)
        return
    rows_per_chunk = max(1_000, task.chunk_size // max(1, len(POLLUTANT_COLUMNS)))
    for chunk in pd.read_csv(
        path,
        chunksize=rows_per_chunk,
        usecols=lambda c: c in USECOLS,
        low_memory=False,
    ):
        frame = _prepare(chunk, task)
        frame["pollutant"] = frame["_pollutant"].map(
            {
                "pm10": "pm10",
                "pm2_5": "pm25",
                "nitrogen_dioxide": "no2",
                "ozone": "o3",
                "sulphur_dioxide": "so2",
                "carbon_monoxide": "co",
                "dust": "dust",
            }
        )
        frame = frame.drop(columns="_pollutant")
        frame["aggregation"] = "hour"
        if not forecast:
            frame["issued_utc"] = pd.NaT
        yield add_provenance(
            frame,
            source=FORECAST_NAME if forecast else NAME,
            value_type=MODEL,
            aggregation="hour",
        )


def read(task: Task):
    yield from _iter(task.root / FILES[NAME], task, forecast=False)


def read_forecast(task: Task):
    yield from _iter(task.root / FILES[FORECAST_NAME], task, forecast=True)


SPEC = SourceSpec(
    name=NAME,
    value_type=MODEL,
    priority=None,
    description="CAMS Europe 0.1° hourly PM10/PM2.5/NO2/O3/SO2/CO/dust, 2016-2026, 8 points.",
    reader=read,
)

FORECAST_SPEC = SourceSpec(
    name=FORECAST_NAME,
    value_type=MODEL,
    priority=None,
    description="CAMS forecast issued 13 Nov 2026 (4 days ahead), same 8 points.",
    reader=read_forecast,
)
