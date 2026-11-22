"""Tests for the harmonised dataset pipeline.

Run with:  pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from airdata.build import build_dataset
from airdata.cli import main
from airdata.schema import ALL_COLUMNS, CORE_COLUMNS, SCHEMA, canonical_pollutant
from airdata.stations import build_registry
from airdata.validation import SourceStats, prepare_chunk

ROOT = Path(__file__).resolve().parents[2]  # modeling/tests -> repo root
DATA_READY = (ROOT / "01_meritve" / "arso_lj_pm_urno_2016_2026.csv.gz").exists()
pytestmark = pytest.mark.skipif(not DATA_READY, reason="ADA Hack data package not present")


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PM10", "pm10"),
        ("pm2.5", "pm25"),
        ("PM2_5", "pm25"),
        ("nitrogen_dioxide", "no2"),
        ("ozone", "o3"),
        ("sulphur_dioxide", "so2"),
        ("carbon_monoxide", "co"),
        ("benzen", "benzene"),
    ],
)
def test_canonical_pollutant(raw: str, expected: str) -> None:
    assert canonical_pollutant(raw) == expected


def test_canonical_pollutant_unknown_raises() -> None:
    with pytest.raises(ValueError):
        canonical_pollutant("unobtainium")


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_unifies_arso_and_eea_codes() -> None:
    registry = build_registry(ROOT)
    assert registry.by_eea("SI0003A") == "E403"
    assert registry.by_arso("E403") == "E403"
    assert registry.by_sensor("purpleair", 96479) == "PA_96479"
    assert registry.by_sensor("sensor_community", "9821") == "SC_9821"
    assert registry.altitude("E403") == pytest.approx(299.0, abs=0.5)


def test_registry_station_table_has_core_columns() -> None:
    rows = pd.DataFrame(build_registry(ROOT).rows())
    for column in ("station_id", "station_name", "lat", "lon", "altitude_m"):
        assert column in rows.columns


# ---------------------------------------------------------------------------
# chunk validation
# ---------------------------------------------------------------------------


def _frame(**overrides) -> pd.DataFrame:
    base = pd.DataFrame(
        {
            "time": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", None],
                utc=True,
            ),
            "lat": [46.0, None, 46.0],
            "lon": [14.5, 14.5, 14.5],
            "altitude_m": [300.0, 300.0, None],
            "pollutant": ["PM10", "PM10", "PM10"],
            "value": [10.0, 11.0, 12.0],
            "unit": ["µg/m³"] * 3,
            "source": ["test"] * 3,
            "value_type": ["measurement"] * 3,
            "station_id": ["E403"] * 3,
            "station_name": ["LJ Bežigrad"] * 3,
            "aggregation": ["hour"] * 3,
            "quality": ["ok"] * 3,
            "quality_detail": [None] * 3,
            "altitude_source": ["station_metadata"] * 3,
            "lead_h": [None] * 3,
            "issued_utc": [pd.NaT] * 3,
            "station_source_code": ["E403"] * 3,
        }
    )
    for key, value in overrides.items():
        base[key] = value
    return base


def test_prepare_chunk_drops_bad_rows_and_dedupes() -> None:
    stats = SourceStats(name="test", value_type="measurement")
    frame = _frame()
    # duplicate of the first row
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    clean = prepare_chunk(frame, stats)
    assert len(clean) == 1  # only the first row is valid and unique
    assert stats.dropped_missing_time >= 1
    assert stats.dropped_missing_coords >= 1
    assert stats.dropped_duplicates == 1
    assert clean["pollutant"].iloc[0] == "pm10"
    assert str(clean["time"].dtype).startswith("datetime64")


# ---------------------------------------------------------------------------
# end-to-end builds
# ---------------------------------------------------------------------------


def _read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def test_build_small_dataset(tmp_path: Path) -> None:
    result = build_dataset(
        root=ROOT,
        out=tmp_path,
        sources="arso_pm",
        limit=750,
        include_primary=True,
    )
    assert result.rows == 750
    dataset = _read(tmp_path / "lj_air.parquet")
    assert list(dataset.columns) == list(ALL_COLUMNS)
    assert len(dataset) == 750
    assert dataset["value"].notna().all()
    assert dataset["time"].notna().all()
    assert str(dataset["time"].dt.tz) == "UTC"
    assert dataset["altitude_m"].notna().all()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "stations.csv").exists()
    assert (tmp_path / "data_dictionary.md").exists()

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["rows"] == 750
    assert manifest["sources"]["arso_pm"]["rows_written"] == 750

    primary = _read(tmp_path / "lj_air_primary.parquet")
    assert len(primary) == 750
    assert main(["verify", "--path", str(tmp_path)]) == 0


def test_build_core_only(tmp_path: Path) -> None:
    build_dataset(root=ROOT, out=tmp_path, sources="gral", limit=120, core_only=True)
    dataset = _read(tmp_path / "lj_air.parquet")
    assert list(dataset.columns) == list(CORE_COLUMNS)
    assert dataset["pollutant"].isin(["pm10"]).all()
    assert dataset["value"].notna().all()


def test_build_time_window(tmp_path: Path) -> None:
    build_dataset(
        root=ROOT,
        out=tmp_path,
        sources="arso_pm",
        start="2020-01-01T00:00:00Z",
        end="2020-02-01T00:00:00Z",
        include_primary=False,
    )
    dataset = _read(tmp_path / "lj_air.parquet")
    assert not dataset.empty
    assert dataset["time"].min() >= pd.Timestamp("2020-01-01T00:00:00Z")
    assert dataset["time"].max() < pd.Timestamp("2020-02-01T00:00:00Z")


def test_primary_prefers_official_arso_over_live(tmp_path: Path) -> None:
    build_dataset(
        root=ROOT,
        out=tmp_path,
        sources="arso_pm,arso_live",
        start="2026-11-13T00:00:00Z",
        end="2026-11-21T00:00:00Z",
        include_primary=True,
    )
    primary = _read(tmp_path / "lj_air_primary.parquet")
    key = (primary["station_id"] == "E403") & (primary["pollutant"] == "pm10")
    assert key.any()
    assert (primary.loc[key, "source"] == "arso_pm").all()


def test_sensor_community_altitude_from_dem(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    dem = ROOT / "04_prostor" / "dem_lj_kotlina_30m.tif"
    if not dem.exists():
        pytest.skip("DEM not available")
    build_dataset(root=ROOT, out=tmp_path, sources="sensor_community", limit=200, include_primary=False)
    dataset = _read(tmp_path / "lj_air.parquet")
    assert dataset["altitude_m"].notna().all()
    assert set(dataset["altitude_source"]) == {"dem_30m"}
    assert dataset["altitude_m"].between(250, 350).all()
