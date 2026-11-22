"""Station / point registry built from the metadata files of the data package.

The registry gives every source a *unified* ``station_id`` so that the same
physical station reported by ARSO and by EEA (different codes) collapses to one
identifier.  Unified ids are:

* ARSO stations .......... ``E403`` (their ARSO code)
* EEA-only stations ...... ``SI0054A`` (their EEA/EoI code)
* PurpleAir devices ...... ``PA_96479``
* Sensor.Community ....... ``SC_9821``

The original code is kept in the ``station_source_code`` column of the dataset.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

M_PER_DEG = 111_320.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p = math.pi / 180.0
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 12742.0 * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class Station:
    """One physical measurement site or model point."""

    station_id: str
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    altitude_m: float | None = None
    altitude_source: str = "unknown"
    kind: str = "unknown"  # arso | eea | purpleair | sensor_community | cams_point
    codes: dict[str, str] = field(default_factory=dict)

    def merge(self, other: "Station") -> None:
        """Fill empty fields from *other* (never overwrite known values)."""
        for attr in ("name", "lat", "lon", "altitude_m"):
            if getattr(self, attr) is None and getattr(other, attr) is not None:
                setattr(self, attr, getattr(other, attr))
                if attr == "altitude_m":
                    self.altitude_source = other.altitude_source
        for key, value in other.codes.items():
            self.codes.setdefault(key, value)


class StationRegistry:
    """Lookup helpers around a dict of :class:`Station`."""

    def __init__(self, stations: dict[str, Station] | None = None) -> None:
        self.stations: dict[str, Station] = stations or {}
        self._arso: dict[str, str] = {}
        self._eea: dict[str, str] = {}
        self._sensor: dict[tuple[str, str], str] = {}
        self._reindex()

    # -- construction -------------------------------------------------
    def add(self, station: Station) -> Station:
        if station.station_id in self.stations:
            self.stations[station.station_id].merge(station)
            return self.stations[station.station_id]
        self.stations[station.station_id] = station
        self._index_one(station)
        return station

    def _reindex(self) -> None:
        self._arso.clear()
        self._eea.clear()
        self._sensor.clear()
        for st in self.stations.values():
            self._index_one(st)

    def _index_one(self, st: Station) -> None:
        if code := st.codes.get("arso"):
            self._arso[code] = st.station_id
        if code := st.codes.get("eea"):
            self._eea[code] = st.station_id
        if st.kind == "purpleair":
            self._sensor[("purpleair", st.station_id.removeprefix("PA_"))] = st.station_id
        if st.kind == "sensor_community":
            self._sensor[("sensor_community", st.station_id.removeprefix("SC_"))] = st.station_id

    # -- lookups ------------------------------------------------------
    def get(self, station_id: str) -> Station | None:
        return self.stations.get(station_id)

    def by_arso(self, code: str) -> str:
        return self._arso.get(str(code), str(code))

    def by_eea(self, code: str) -> str:
        return self._eea.get(str(code), str(code))

    def by_sensor(self, source: str, sensor_id: object) -> str:
        sid = str(sensor_id).strip()
        if sid.endswith(".0"):
            sid = sid[:-2]
        found = self._sensor.get((source, sid))
        if found:
            return found
        prefix = "PA" if source == "purpleair" else "SC"
        return f"{prefix}_{sid}"

    def altitude(self, station_id: str) -> float | None:
        st = self.stations.get(station_id)
        return None if st is None else st.altitude_m

    def nearest(self, lat: float, lon: float, max_km: float = 15.0) -> Station | None:
        best: Station | None = None
        best_d = float("inf")
        for st in self.stations.values():
            if st.lat is None or st.lon is None:
                continue
            d = haversine_km(lat, lon, st.lat, st.lon)
            if d < best_d:
                best, best_d = st, d
        if best is None or best_d > max_km:
            return None
        return best

    def rows(self) -> list[dict[str, object]]:
        """Flat station table (used for ``stations.csv``)."""
        out = []
        for st in sorted(self.stations.values(), key=lambda s: s.station_id):
            out.append(
                {
                    "station_id": st.station_id,
                    "station_name": st.name,
                    "lat": st.lat,
                    "lon": st.lon,
                    "altitude_m": st.altitude_m,
                    "altitude_source": st.altitude_source,
                    "station_kind": st.kind,
                    "arso_code": st.codes.get("arso"),
                    "eea_code": st.codes.get("eea"),
                    "sensor_source": st.kind if st.kind in ("purpleair", "sensor_community") else None,
                    "sensor_id": (
                        st.station_id.split("_", 1)[1]
                        if st.kind in ("purpleair", "sensor_community")
                        else None
                    ),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Builders for the individual metadata files
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _features(doc: dict) -> list[dict]:
    return doc.get("features", [])


def _point_lonlat(feature: dict) -> tuple[float | None, float | None]:
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        return None, None
    return float(coords[0]), float(coords[1])


def _load_arso_pm(root: Path, registry: StationRegistry) -> None:
    path = root / "01_meritve" / "arso_lj_postaje.geojson"
    if not path.exists():
        return
    for feat in _features(_read_json(path)):
        p = feat.get("properties", {})
        lon, lat = _point_lonlat(feat)
        code = str(p["station_code"])
        registry.add(
            Station(
                station_id=code,
                name=p.get("station_name"),
                lat=lat if lat is not None else p.get("lat"),
                lon=lon if lon is not None else p.get("lon"),
                altitude_m=float(p["alt_m"]) if p.get("alt_m") is not None else None,
                altitude_source="station_metadata",
                kind="arso",
                codes={"arso": code, "eea": str(p["eea_code"]) if p.get("eea_code") else None},
            )
        )


def _load_eea(root: Path, registry: StationRegistry) -> None:
    path = root / "01_meritve" / "eea_postaje.geojson"
    if not path.exists():
        return
    for feat in _features(_read_json(path)):
        p = feat.get("properties", {})
        lon, lat = _point_lonlat(feat)
        eea = str(p["station_code"])
        arso = str(p["arso_code"]) if p.get("arso_code") else None
        sid = arso or eea
        registry.add(
            Station(
                station_id=sid,
                name=p.get("station_name"),
                lat=lat,
                lon=lon,
                altitude_m=float(p["alt_m"]) if p.get("alt_m") is not None else None,
                altitude_source="eea_metadata",
                kind="eea" if not arso else "arso",
                codes={"arso": arso, "eea": eea},
            )
        )


def _load_purpleair(root: Path, registry: StationRegistry) -> None:
    path = root / "01_meritve" / "purpleair_lj_naprave.geojson"
    if not path.exists():
        return
    for feat in _features(_read_json(path)):
        p = feat.get("properties", {})
        lon, lat = _point_lonlat(feat)
        try:
            sid = int(p["sensor_index"])
        except (KeyError, TypeError, ValueError):
            continue
        registry.add(
            Station(
                station_id=f"PA_{sid}",
                name=p.get("name"),
                lat=lat if lat is not None else p.get("lat"),
                lon=lon if lon is not None else p.get("lon"),
                altitude_m=float(p["alt_m"]) if p.get("alt_m") is not None else None,
                altitude_source="station_metadata",
                kind="purpleair",
            )
        )


def _load_sensor_community(root: Path, registry: StationRegistry) -> None:
    path = root / "01_meritve" / "sensor_community_lj_naprave.geojson"
    if not path.exists():
        return
    for feat in _features(_read_json(path)):
        p = feat.get("properties", {})
        lon, lat = _point_lonlat(feat)
        if p.get("indoor"):
            continue
        try:
            sid = int(p["sensor_id"])
        except (KeyError, TypeError, ValueError):
            continue
        registry.add(
            Station(
                station_id=f"SC_{sid}",
                name=f"Sensor.Community {sid}",
                lat=lat if lat is not None else p.get("lat"),
                lon=lon if lon is not None else p.get("lon"),
                altitude_m=None,
                altitude_source="unknown",
                kind="sensor_community",
            )
        )


def _load_camx_points(root: Path, registry: StationRegistry) -> None:
    path = root / "02_modeli" / "camx" / "camx_tocke.csv"
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = row.get("point_id")
            if not pid:
                continue
            if pid in registry.stations:
                continue
            registry.add(
                Station(
                    station_id=pid,
                    name=row.get("name"),
                    lat=float(row["lat"]) if row.get("lat") else None,
                    lon=float(row["lon"]) if row.get("lon") else None,
                    altitude_m=None,
                    altitude_source="unknown",
                    kind="cams_point",
                    codes={"arso": pid} if str(row.get("vrsta", "")).startswith("postaja") else {},
                )
            )


def _load_live_stations(root: Path, registry: StationRegistry) -> None:
    path = root / "05_zadnji_dnevi" / "arso_live_urno_vse_postaje.csv"
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row.get("station_code")
            if not code:
                continue
            sid = registry.by_arso(code)
            st = registry.get(sid)
            if st is None:
                st = registry.add(
                    Station(
                        station_id=code,
                        name=row.get("station_name"),
                        kind="arso",
                        codes={"arso": code},
                    )
                )
            if st.lat is None and row.get("lat"):
                st.lat = float(row["lat"])
            if st.lon is None and row.get("lon"):
                st.lon = float(row["lon"])
            if st.altitude_m is None and row.get("alt_m"):
                st.altitude_m = float(row["alt_m"])
                st.altitude_source = "station_metadata"
            registry.add(st)


def build_registry(root: Path) -> StationRegistry:
    """Build the unified station registry from every metadata file present."""
    registry = StationRegistry()
    # EEA first: it carries the arso<->eea code mapping and altitudes.
    for loader in (
        _load_eea,
        _load_arso_pm,
        _load_purpleair,
        _load_sensor_community,
        _load_camx_points,
        _load_live_stations,
    ):
        loader(root, registry)
    registry._reindex()
    return registry
