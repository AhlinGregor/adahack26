"""Per-chunk cleaning, validation and statistics."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schema import ALL_COLUMNS, ROW_KEY, canonical_pollutant_series

#: Rough bounding box of the Ljubljana basin plus its reference sites
#: (Pasja ravan, Krvavec, Zasavje).  Used only for *reporting* how many rows
#: fall outside the area of interest, never for dropping rows by default.
BASIN_BBOX = (45.75, 14.10, 46.40, 15.10)

SL_BBOX = (45.40, 13.30, 46.90, 16.70)  # Slovenia


@dataclass
class SourceStats:
    """Accumulated counters and coverage of one source."""

    name: str
    value_type: str
    rows_read: int = 0
    rows_written: int = 0
    dropped_missing_time: int = 0
    dropped_missing_coords: int = 0
    dropped_missing_value: int = 0
    dropped_missing_pollutant: int = 0
    dropped_outside_bounds: int = 0
    dropped_outside_filter_bbox: int = 0
    dropped_outside_time: int = 0
    dropped_duplicates: int = 0
    negative_values: int = 0
    outside_basin_rows: int = 0
    altitude_missing: int = 0
    duplicates_across_chunks: int = 0
    pollutants: set[str] = field(default_factory=set)
    stations: set[str] = field(default_factory=set)
    frame_sources: set[str] = field(default_factory=set)
    time_min: pd.Timestamp | None = None
    time_max: pd.Timestamp | None = None

    @property
    def value_types(self) -> list[str]:
        return [self.value_type]

    def observe_time(self, times: pd.Series) -> None:
        if times.empty:
            return
        lo, hi = times.min(), times.max()
        if pd.notna(lo) and (self.time_min is None or lo < self.time_min):
            self.time_min = lo
        if pd.notna(hi) and (self.time_max is None or hi > self.time_max):
            self.time_max = hi

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value_type": self.value_type,
            "rows_read": self.rows_read,
            "rows_written": self.rows_written,
            "dropped": {
                "missing_time": self.dropped_missing_time,
                "missing_coordinates": self.dropped_missing_coords,
                "missing_value": self.dropped_missing_value,
                "missing_pollutant": self.dropped_missing_pollutant,
                "outside_global_bounds": self.dropped_outside_bounds,
                "outside_filter_bbox": self.dropped_outside_filter_bbox,
                "outside_time_window": self.dropped_outside_time,
                "duplicates": self.dropped_duplicates,
            },
            "negative_values_kept": self.negative_values,
            "duplicates_across_chunks": self.duplicates_across_chunks,
            "rows_outside_basin_bbox": self.outside_basin_rows,
            "altitude_missing": self.altitude_missing,
            "pollutants": sorted(self.pollutants),
            "stations": len(self.stations),
            "time_min": _iso(self.time_min),
            "time_max": _iso(self.time_max),
        }


def _iso(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    return value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def prepare_chunk(
    frame: pd.DataFrame,
    stats: SourceStats,
    *,
    bbox: tuple[float, float, float, float] | None = None,
) -> pd.DataFrame:
    """Clean one canonical chunk and update *stats*.

    Drops rows that cannot be represented in the dataset (no time, no
    coordinates, no value) and exact duplicates on the dataset key.  All other
    oddities are kept but counted/reported.
    """
    stats.rows_read += len(frame)
    if frame.empty:
        return frame

    df = frame.copy()
    missing_cols = [c for c in ALL_COLUMNS if c not in df.columns]
    for column in missing_cols:
        df[column] = None

    # --- time ---------------------------------------------------------
    df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    bad_time = df["time"].isna()
    stats.dropped_missing_time += int(bad_time.sum())
    df = df.loc[~bad_time]

    # --- coordinates --------------------------------------------------
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    bad_coords = df["lat"].isna() | df["lon"].isna()
    stats.dropped_missing_coords += int(bad_coords.sum())
    df = df.loc[~bad_coords]

    lat_min, lon_min, lat_max, lon_max = SL_BBOX
    outside = ~df["lat"].between(lat_min, lat_max) | ~df["lon"].between(lon_min, lon_max)
    stats.dropped_outside_bounds += int(outside.sum())
    df = df.loc[~outside]

    if bbox is not None:
        inside = (
            df["lat"].between(bbox[0], bbox[2]) & df["lon"].between(bbox[1], bbox[3])
        )
        stats.dropped_outside_filter_bbox += int((~inside).sum())
        df = df.loc[inside]

    # --- values -------------------------------------------------------
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    bad_value = df["value"].isna() | ~np.isfinite(df["value"].to_numpy(dtype="float64"))
    stats.dropped_missing_value += int(bad_value.sum())
    df = df.loc[~bad_value].copy()


    # --- pollutants ---------------------------------------------------
    df["pollutant"] = canonical_pollutant_series(df["pollutant"])
    bad_pollutant = df["pollutant"].isna() | (df["pollutant"].astype("string").str.len() == 0)
    stats.dropped_missing_pollutant += int(bad_pollutant.sum())
    df = df.loc[~bad_pollutant]

    # --- altitude -----------------------------------------------------
    df["altitude_m"] = pd.to_numeric(df["altitude_m"], errors="coerce")

    # --- duplicates inside the chunk ----------------------------------
    duplicates = df.duplicated(subset=list(ROW_KEY))
    stats.dropped_duplicates += int(duplicates.sum())
    df = df.loc[~duplicates]

    # --- final dtypes -------------------------------------------------
    df["value"] = df["value"].astype("float32")
    df["altitude_m"] = df["altitude_m"].astype("float32")
    df["lat"] = df["lat"].astype("float64")
    df["lon"] = df["lon"].astype("float64")
    df["lead_h"] = pd.to_numeric(df["lead_h"], errors="coerce").astype("Int16")
    df["issued_utc"] = pd.to_datetime(df["issued_utc"], errors="coerce", utc=True)

    string_columns = [
        "unit",
        "source",
        "value_type",
        "station_id",
        "station_name",
        "aggregation",
        "quality",
        "quality_detail",
        "altitude_source",
        "station_source_code",
        "pollutant",
    ]
    for column in string_columns:
        df[column] = df[column].astype("object")

    return df
