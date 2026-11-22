"""ARSO CAMx 4.4 km hourly values in the cell of each station/point."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..schema import MODEL
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "camx"
FILE = Path("02_modeli") / "camx" / "camx_tocke_urno_2023_2026.csv.gz"
POINTS_FILE = Path("02_modeli") / "camx" / "camx_tocke.csv"

POLLUTANT_COLUMNS = {
    "camx_pm25": "pm25",
    "camx_pm10": "pm10",
    "camx_o3": "o3",
}

USECOLS = ["run_utc", "lead_h", "time_utc", "point_id"] + list(POLLUTANT_COLUMNS)


def _load_points(root: Path) -> dict[str, dict[str, object]]:
    path = root / POINTS_FILE
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return {
        str(row["point_id"]): {
            "name": row.get("name"),
            "lat": float(row["lat"]) if pd.notna(row.get("lat")) else None,
            "lon": float(row["lon"]) if pd.notna(row.get("lon")) else None,
        }
        for _, row in df.iterrows()
    }


def read(task: Task):
    path = task.root / FILE
    if not path.exists():
        log.warning("missing input %s", path)
        return
    points = _load_points(task.root)

    max_lead = 48 if task.include_camx_tomorrow else 24
    rows_per_chunk = max(1_000, task.chunk_size // max(1, len(POLLUTANT_COLUMNS)))
    for chunk in pd.read_csv(
        path,
        chunksize=rows_per_chunk,
        usecols=lambda c: c in USECOLS,
        low_memory=False,
    ):
        chunk = chunk[chunk["lead_h"] <= max_lead].copy()
        if chunk.empty:
            continue
        chunk["time"] = parse_utc(chunk["time_utc"])
        chunk["issued_utc"] = parse_utc(chunk["run_utc"])
        chunk["lead_h"] = pd.to_numeric(chunk["lead_h"], errors="coerce").astype("Int16")
        chunk["station_id"] = chunk["point_id"]
        chunk["station_source_code"] = chunk["point_id"]
        chunk["station_name"] = chunk["point_id"].map(lambda p: points.get(p, {}).get("name"))
        chunk["lat"] = chunk["point_id"].map(lambda p: points.get(p, {}).get("lat"))
        chunk["lon"] = chunk["point_id"].map(lambda p: points.get(p, {}).get("lon"))

        altitude = chunk["station_id"].map(task.registry.altitude)
        chunk["altitude_m"] = pd.to_numeric(altitude, errors="coerce")
        chunk["altitude_source"] = np.where(chunk["altitude_m"].notna(), "station_metadata", None)
        chunk["quality"] = "ok"
        chunk["quality_detail"] = (
            "CAMx 4.4 km cell; lead_h="
            + chunk["lead_h"].astype("string")
            + " (1-24 = same-day forecast, 25-48 = tomorrow forecast)"
        )

        id_cols = [
            "time",
            "issued_utc",
            "lead_h",
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
        long = chunk.melt(
            id_vars=id_cols,
            value_vars=list(POLLUTANT_COLUMNS),
            var_name="_pollutant",
            value_name="value",
        )
        long["pollutant"] = long["_pollutant"].map(POLLUTANT_COLUMNS)
        long = long.drop(columns="_pollutant")

        yield add_provenance(long, source=NAME, value_type=MODEL, aggregation="hour")


SPEC = SourceSpec(
    name=NAME,
    value_type=MODEL,
    priority=None,
    description="ARSO CAMx 4.4 km hourly PM2.5/PM10/O3 in station cells, 2023-2026 (same-day forecast).",
    reader=read,
)
