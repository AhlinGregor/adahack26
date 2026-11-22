"""Shared plumbing for source readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

import numpy as np
import pandas as pd

from ..altitude import AltitudeResolver
from ..schema import (
    ALL_COLUMNS,
    DEFAULT_UNIT,
    canonical_pollutant_series,
)
from ..stations import StationRegistry


@dataclass
class Task:
    """Everything a reader needs besides its own file paths."""

    root: Path
    registry: StationRegistry
    altitude: AltitudeResolver
    chunk_size: int = 250_000
    include_camx_tomorrow: bool = False
    limit: int | None = None


Reader = Callable[[Task], Iterator[pd.DataFrame]]


@dataclass(frozen=True)
class SourceSpec:
    """Description of one input source."""

    name: str
    value_type: str
    priority: int | None
    description: str
    reader: Reader

    @property
    def in_primary_view(self) -> bool:
        return self.priority is not None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def parse_utc(series: pd.Series) -> pd.Series:
    """Parse ISO-8601 strings (with or without ``Z``) into UTC timestamps."""
    return pd.to_datetime(series, errors="coerce", utc=True)


def parse_fixed_utc_plus_1(series: pd.Series) -> pd.Series:
    """Parse naive local times that are UTC+1 all year (ARSO convention)."""
    naive = pd.to_datetime(series, errors="coerce")
    return (naive - pd.Timedelta(hours=1)).dt.tz_localize("UTC")


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------


def melt_pollutants(
    df: pd.DataFrame,
    value_columns: Iterable[str],
    id_columns: Iterable[str],
) -> pd.DataFrame:
    """Melt a wide (one column per pollutant) frame into long form."""
    value_columns = [c for c in value_columns if c in df.columns]
    long = df.melt(
        id_vars=list(id_columns),
        value_vars=value_columns,
        var_name="_pollutant_raw",
        value_name="value",
    )
    long["pollutant"] = canonical_pollutant_series(long["_pollutant_raw"])
    long = long.drop(columns="_pollutant_raw")
    return long


def add_provenance(
    frame: pd.DataFrame,
    *,
    source: str,
    value_type: str,
    aggregation: str,
    unit: str = DEFAULT_UNIT,
) -> pd.DataFrame:
    """Attach constant provenance columns and enforce the canonical order."""
    frame = frame.copy()
    frame["unit"] = unit
    frame["source"] = source
    frame["value_type"] = value_type
    frame["aggregation"] = aggregation
    for column in (
        "station_id",
        "station_name",
        "altitude_m",
        "quality",
        "quality_detail",
        "altitude_source",
        "lead_h",
        "issued_utc",
        "station_source_code",
    ):
        if column not in frame.columns:
            frame[column] = None
    return frame.loc[:, ALL_COLUMNS]


def fill_missing_coords(frame: pd.DataFrame, registry: StationRegistry) -> pd.DataFrame:
    """Use the station registry to fill missing lat/lon/altitude for known ids."""
    if "station_id" not in frame.columns:
        return frame
    for column in ("lat", "lon", "altitude_m"):
        if column not in frame.columns:
            frame[column] = np.nan
    if "altitude_source" not in frame.columns:
        frame["altitude_source"] = None

    missing = frame["lat"].isna() | frame["lon"].isna()
    if not missing.any():
        return frame

    ids = frame.loc[missing, "station_id"]
    stations = ids.map(lambda sid: registry.get(sid) if isinstance(sid, str) else None)
    lat_fill = pd.to_numeric(stations.map(lambda st: None if st is None else st.lat), errors="coerce")
    lon_fill = pd.to_numeric(stations.map(lambda st: None if st is None else st.lon), errors="coerce")
    alt_fill = pd.to_numeric(stations.map(lambda st: None if st is None else st.altitude_m), errors="coerce")

    frame.loc[missing, "lat"] = frame.loc[missing, "lat"].fillna(lat_fill)
    frame.loc[missing, "lon"] = frame.loc[missing, "lon"].fillna(lon_fill)
    altitude_before = frame["altitude_m"].copy()
    frame.loc[missing, "altitude_m"] = frame.loc[missing, "altitude_m"].fillna(alt_fill)
    filled_altitude = frame["altitude_m"].notna() & altitude_before.isna()
    frame.loc[filled_altitude, "altitude_source"] = "station_metadata"
    return frame


def parse_below_detection(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Parse ARSO values like ``<2`` into (value, flagged).

    Values below the detection limit are stored as half the limit, the
    convention used elsewhere in the data package.
    """
    text = series.astype("string").str.strip()
    flagged = text.str.startswith("<").fillna(False).astype(bool)
    numeric = pd.to_numeric(text.str.lstrip("<> ").str.strip(), errors="coerce").astype("float64")
    numeric = numeric.where(~flagged, numeric / 2.0)
    return numeric, flagged
