"""Spatial helpers: distance-weighted regional background and IDW maps.

Coordinates are used in two places:

* inference – forecasts at an arbitrary (lat, lon) are blended from the k
  nearest station forecasts with inverse-distance weights;
* evaluation – the same leave-one-out IDW blend is scored against the held-out
  station measurements to show how well the spatial layer works.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def haversine_matrix(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    p = math.pi / 180.0
    lat = np.asarray(lats, dtype=float) * p
    lon = np.asarray(lons, dtype=float) * p
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def idw_weights(
    stations: list[str],
    coords: dict[str, tuple[float, float]],
    lat: float,
    lon: float,
    *,
    k: int = 3,
    power: float = 2.0,
    max_km: float = 60.0,
) -> list[tuple[str, float, float]]:
    """Return ``(station_id, distance_km, normalised_weight)`` for the k nearest."""
    candidates = []
    for station in stations:
        if station not in coords:
            continue
        slat, slon = coords[station]
        distance = haversine_km(lat, lon, slat, slon)
        if distance <= max_km:
            candidates.append((station, distance))
    candidates.sort(key=lambda item: item[1])
    candidates = candidates[:k]
    if not candidates:
        return []
    raw = [(station, distance, 1.0 / (distance + 1.0) ** power) for station, distance in candidates]
    total = sum(weight for _, _, weight in raw)
    return [(station, distance, weight / total) for station, distance, weight in raw]
