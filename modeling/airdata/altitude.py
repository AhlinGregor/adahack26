"""Altitude enrichment.

Sources either carry the station altitude in their own metadata (ARSO, EEA,
PurpleAir, CAMS model cells) or not (Sensor.Community, GRAL points).  For the
latter, the 30 m Copernicus DEM of the Ljubljana basin is sampled; if the DEM
is unavailable or the point falls outside it, the altitude of the nearest known
station within 15 km is used.  The provenance is stored per row in
``altitude_source``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .stations import StationRegistry

log = logging.getLogger(__name__)

DEM_RELATIVE_PATH = Path("04_prostor") / "dem_lj_kotlina_30m.tif"
_COORD_DECIMALS = 6


class DemSampler:
    """Lazily opened 30 m DEM with a per-point cache."""

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._cache: dict[tuple[float, float], float | None] = {}
        self._dataset = None
        self._failed = False

    @property
    def available(self) -> bool:
        return self.path is not None and self.path.exists() and not self._failed

    def _open(self):
        if self._dataset is not None:
            return self._dataset
        try:  # pragma: no cover - depends on optional rasterio
            import rasterio

            self._dataset = rasterio.open(self.path)
        except Exception as exc:  # pragma: no cover
            log.warning("DEM not usable (%s): %s", self.path, exc)
            self._failed = True
            self._dataset = None
        return self._dataset

    def sample(self, lat: float, lon: float) -> float | None:
        key = (round(lat, _COORD_DECIMALS), round(lon, _COORD_DECIMALS))
        if key in self._cache:
            return self._cache[key]
        value: float | None = None
        ds = self._open()
        if ds is not None:
            bounds = ds.bounds
            if bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top:
                try:
                    arr = next(ds.sample([(lon, lat)]))
                    raw = float(arr[0])
                    nodata = ds.nodata
                    if np.isfinite(raw) and (nodata is None or raw != nodata) and -100.0 < raw < 9000.0:
                        value = raw
                except Exception:  # pragma: no cover - point outside raster
                    value = None
        self._cache[key] = value
        return value

    def close(self) -> None:
        if self._dataset is not None:
            self._dataset.close()
            self._dataset = None


class AltitudeResolver:
    """Fill missing ``altitude_m`` values of a canonical frame."""

    def __init__(self, registry: StationRegistry, dem_path: Path | None) -> None:
        self.registry = registry
        self.dem = DemSampler(dem_path)

    def fill(self, df: pd.DataFrame) -> pd.DataFrame:
        if "altitude_m" not in df.columns:
            df["altitude_m"] = np.nan
        if "altitude_source" not in df.columns:
            df["altitude_source"] = None

        missing = df["altitude_m"].isna()
        if not missing.any():
            df["altitude_source"] = df["altitude_source"].fillna("unknown")
            return df

        coords = (
            df.loc[missing, ["lat", "lon"]]
            .assign(
                _lat_key=lambda d: d["lat"].round(_COORD_DECIMALS),
                _lon_key=lambda d: d["lon"].round(_COORD_DECIMALS),
            )
            .loc[:, ["_lat_key", "_lon_key"]]
            .drop_duplicates()
        )
        mapping: dict[tuple[float, float], tuple[float | None, str]] = {}
        for lat_key, lon_key in coords.itertuples(index=False):
            value = self.dem.sample(float(lat_key), float(lon_key)) if self.dem.available else None
            if value is not None:
                mapping[(lat_key, lon_key)] = (value, "dem_30m")
                continue
            near = self.registry.nearest(float(lat_key), float(lon_key), max_km=15.0)
            if near is not None and near.altitude_m is not None:
                mapping[(lat_key, lon_key)] = (near.altitude_m, "nearest_station")
            else:
                mapping[(lat_key, lon_key)] = (None, "unknown")

        lat_key = df["lat"].round(_COORD_DECIMALS)
        lon_key = df["lon"].round(_COORD_DECIMALS)
        alt = [mapping.get((a, b), (None, "unknown"))[0] for a, b in zip(lat_key, lon_key)]
        src = [mapping.get((a, b), (None, "unknown"))[1] for a, b in zip(lat_key, lon_key)]
        df["altitude_m"] = np.where(missing, alt, df["altitude_m"])
        df["altitude_source"] = np.where(
            missing, src, df["altitude_source"].fillna("unknown")
        )
        return df

    def close(self) -> None:
        self.dem.close()
