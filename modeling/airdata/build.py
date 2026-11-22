"""Orchestration: read every selected source into one tidy long dataset."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .altitude import DEM_RELATIVE_PATH, AltitudeResolver
from .paths import find_data_root
from .io import CsvSink, ParquetSink
from .schema import (
    ALL_COLUMNS,
    CORE_COLUMNS,
    CORE_SCHEMA,
    PRIMARY_KEY,
    ROW_KEY,
    SCHEMA,
)
from .sources import ALL_SPECS, SourceSpec, Task, resolve_sources
from .stations import StationRegistry, build_registry
from .validation import BASIN_BBOX, SourceStats, prepare_chunk

log = logging.getLogger(__name__)

FULL_STEM = "lj_air"
PRIMARY_STEM = "lj_air_primary"

PRIORITY: dict[str, int] = {
    spec.name: spec.priority for spec in ALL_SPECS if spec.priority is not None
}


@dataclass
class BuildResult:
    out_dir: Path
    rows: int
    primary_rows: int | None
    manifest: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"dataset : {self.out_dir}",
            f"rows    : {self.rows:,}",
            f"primary : {self.primary_rows:,}" if self.primary_rows is not None else "primary : skipped",
        ]
        return "\n".join(lines)


class _TeeSink:
    def __init__(self, sinks: list) -> None:
        self.sinks = sinks

    def write(self, frame: pd.DataFrame) -> None:
        for sink in self.sinks:
            sink.write(frame)

    def close(self) -> None:
        for sink in self.sinks:
            sink.close()

    @property
    def rows(self) -> int:
        return self.sinks[0].rows if self.sinks else 0


def _parse_time_bound(value: str | None, label: str) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - argparse validates
        raise ValueError(f"Invalid --{label}: {value!r}") from exc
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox expects min_lat,min_lon,max_lat,max_lon")
    return parts[0], parts[1], parts[2], parts[3]


def _attach_altitudes(frame: pd.DataFrame, resolver: AltitudeResolver) -> pd.DataFrame:
    required = {"lat", "lon", "altitude_m"}
    if not required.issubset(frame.columns):
        return frame
    return resolver.fill(frame)


def build_primary(
    measurements_path: Path,
    output_path: Path,
    schema: pa.Schema,
    *,
    chunk_rows: int = 200_000,
) -> int:
    """Build the de-duplicated measurement-only view.

    For the same (station, time, pollutant, aggregation) the highest-priority
    source wins: ARSO direct > ARSO live > EEA > PurpleAir > Sensor.Community.
    """
    if not measurements_path.exists():
        return 0
    key_cols = ["station_id", "time", "pollutant", "aggregation", "source"]
    keys = pd.read_parquet(measurements_path, columns=key_cols)
    if keys.empty:
        ParquetSink(output_path, schema).close()
        return 0

    for column in ("station_id", "pollutant", "aggregation", "source"):
        keys[column] = keys[column].astype("category")

    priority = keys["source"].astype("object").map(PRIORITY)
    if priority.isna().any():  # pragma: no cover - registry and source names must agree
        unknown = sorted(keys.loc[priority.isna(), "source"].unique())
        raise ValueError(f"Measurement source without priority: {unknown}")
    priority = priority.astype("int8").to_numpy()

    order = np.argsort(priority, kind="stable")
    ordered = keys.iloc[order]
    keep_in_order = ~ordered.duplicated(subset=list(PRIMARY_KEY), keep="first")
    keep = np.zeros(len(keys), dtype=bool)
    keep[order[keep_in_order.to_numpy()]] = True

    sink = ParquetSink(output_path, schema)
    try:
        parquet = pq.ParquetFile(measurements_path)
        offset = 0
        for batch in parquet.iter_batches(batch_size=chunk_rows):
            n = batch.num_rows
            selection = keep[offset : offset + n]
            offset += n
            if selection.any():
                sink.write(batch.filter(pa.array(selection)).to_pandas())
    finally:
        sink.close()
    return sink.rows


def _collect_hashes(frames_hashes: list[np.ndarray]) -> np.ndarray:
    if not frames_hashes:
        return np.empty(0, dtype=np.uint64)
    return np.concatenate(frames_hashes)


def build_dataset(
    *,
    root: str | Path | None = None,
    out: str | Path | None = None,
    sources: str | None = None,
    exclude: str | None = None,
    chunk_size: int = 250_000,
    include_camx_tomorrow: bool = False,
    start: str | None = None,
    end: str | None = None,
    bbox: str | None = None,
    formats: str = "parquet",
    core_only: bool = False,
    include_primary: bool = True,
    limit: int | None = None,
    dem: str | None = None,
) -> BuildResult:
    """Build the harmonised dataset and return a summary."""
    started = time.time()
    root = find_data_root(root)
    if out is None:
        from .paths import default_output_dir

        out_dir = default_output_dir()
    else:
        out_dir = Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = resolve_sources(sources, exclude)
    if not specs:
        raise ValueError("No sources selected")
    if core_only and include_primary:
        log.warning("--core-only implies --no-primary (the primary view needs station metadata)")
        include_primary = False

    output_formats = {f.strip().lower() for f in formats.split(",") if f.strip()}
    unknown_formats = output_formats - {"parquet", "csv"}
    if unknown_formats:
        raise ValueError(f"Unknown output format(s): {sorted(unknown_formats)}")

    start_ts = _parse_time_bound(start, "start")
    end_ts = _parse_time_bound(end, "end")
    bbox_filter = _parse_bbox(bbox)

    dem_path = Path(dem).resolve() if dem else root / DEM_RELATIVE_PATH
    registry = build_registry(root)
    resolver = AltitudeResolver(registry, dem_path if dem_path.exists() else None)
    task = Task(
        root=root,
        registry=registry,
        altitude=resolver,
        chunk_size=chunk_size,
        include_camx_tomorrow=include_camx_tomorrow,
        limit=limit,
    )

    columns = CORE_COLUMNS if core_only else ALL_COLUMNS
    schema = CORE_SCHEMA if core_only else SCHEMA
    main_sinks: list = []
    if "parquet" in output_formats:
        main_sinks.append(ParquetSink(out_dir / f"{FULL_STEM}.parquet", schema))
    if "csv" in output_formats:
        main_sinks.append(CsvSink(out_dir / f"{FULL_STEM}.csv.gz", columns))
    if not main_sinks:
        raise ValueError("No output format selected")
    main_sink = _TeeSink(main_sinks)

    measurements_path = out_dir / "_measurements.parquet"
    measurement_sink = ParquetSink(measurements_path, SCHEMA) if include_primary else None

    source_stats: dict[str, SourceStats] = {}
    ok = False
    try:
        for spec in specs:
            source_stats[spec.name] = _run_source(
                spec,
                task,
                main_sink,
                measurement_sink if spec.in_primary_view else None,
                start_ts=start_ts,
                end_ts=end_ts,
                bbox=bbox_filter,
                limit=limit,
            )
        ok = True
    finally:
        main_sink.close()
        if measurement_sink is not None:
            measurement_sink.close()
        resolver.close()

    primary_rows: int | None = None
    primary_path = out_dir / f"{PRIMARY_STEM}.parquet"
    if include_primary and ok:
        primary_rows = build_primary(measurements_path, primary_path, SCHEMA, chunk_rows=200_000)
        if measurements_path.exists():
            measurements_path.unlink()
    elif measurements_path.exists():
        measurements_path.unlink()

    # ------------------------------------------------------------------
    # Manifest, station table, documentation
    # ------------------------------------------------------------------
    used_stations: set[str] = set()
    for stats in source_stats.values():
        used_stations.update(stats.stations)

    stations_path = out_dir / "stations.csv"
    pd.DataFrame(registry.rows()).assign(
        in_dataset=lambda d: d["station_id"].isin(used_stations)
    ).to_csv(stations_path, index=False, encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_seconds": round(time.time() - started, 1),
        "root": str(root),
        "out_dir": str(out_dir),
        "parameters": {
            "sources": [spec.name for spec in specs],
            "exclude": exclude,
            "chunk_size": chunk_size,
            "include_camx_tomorrow": include_camx_tomorrow,
            "start": start,
            "end": end,
            "bbox": bbox,
            "formats": sorted(output_formats),
            "core_only": core_only,
            "include_primary": include_primary,
            "limit": limit,
            "dem": str(dem_path) if dem_path.exists() else None,
        },
        "dataset": {
            "file": str(out_dir / f"{FULL_STEM}.parquet"),
            "csv_gz": str(out_dir / f"{FULL_STEM}.csv.gz") if "csv" in output_formats else None,
            "rows": main_sink.rows,
            "columns": list(columns),
        },
        "primary_view": {
            "file": str(primary_path) if primary_rows is not None else None,
            "rows": primary_rows,
            "definition": (
                "measurements only, one row per station_id/time/pollutant/aggregation; "
                "priority arso_pm > arso_live > eea > purpleair > sensor_community"
            ),
        },
        "stations": {
            "file": str(stations_path),
            "rows": len(registry.rows()),
            "in_dataset": len(used_stations),
        },
        "sources": {name: stats.as_dict() for name, stats in source_stats.items()},
        "checks": {
            "all_sources_unique_on_row_key": _all_unique(source_stats),
            "rows_outside_basin_bbox": sum(
                stats.outside_basin_rows for stats in source_stats.values()
            ),
            "negative_values_kept": sum(
                stats.negative_values for stats in source_stats.values()
            ),
            "altitude_missing": sum(
                stats.altitude_missing for stats in source_stats.values()
            ),
        },
        "value_types": {spec.name: spec.value_type for spec in specs},
        "dataset_description": "Tidy long air-quality dataset for the Ljubljana basin.",
        "time_zone": "UTC",
        "unit": "µg/m³",
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    from .docs import write_documentation

    write_documentation(out_dir, manifest=manifest, specs=specs)

    return BuildResult(out_dir=out_dir, rows=main_sink.rows, primary_rows=primary_rows, manifest=manifest)


def _observe(frame: pd.DataFrame, stats: SourceStats) -> None:
    """Accumulate coverage counters for rows that are actually written."""
    stats.observe_time(frame["time"])
    stats.pollutants.update(frame["pollutant"].dropna().unique().tolist())
    stats.stations.update(frame["station_id"].dropna().unique().tolist())
    stats.frame_sources.update(frame["source"].dropna().unique().tolist())
    stats.negative_values += int((frame["value"] < 0).sum())
    stats.altitude_missing += int(frame["altitude_m"].isna().sum())
    inside_basin = frame["lat"].between(BASIN_BBOX[0], BASIN_BBOX[2]) & frame["lon"].between(
        BASIN_BBOX[1], BASIN_BBOX[3]
    )
    stats.outside_basin_rows += int((~inside_basin).sum())


def _all_unique(source_stats: dict[str, "SourceStats"]) -> bool:
    return all(getattr(stats, "duplicates_across_chunks", 0) == 0 for stats in source_stats.values())


def _run_source(
    spec: SourceSpec,
    task: Task,
    main_sink,
    measurement_sink,
    *,
    start_ts: pd.Timestamp | None,
    end_ts: pd.Timestamp | None,
    bbox: tuple[float, float, float, float] | None,
    limit: int | None,
) -> SourceStats:
    stats = SourceStats(name=spec.name, value_type=spec.value_type)
    hashes: list[np.ndarray] = []
    remaining = limit
    started = time.time()
    frames = 0

    for raw in spec.reader(task):
        if remaining is not None and remaining <= 0:
            break
        frames += 1
        frame = _attach_altitudes(raw, task.altitude)
        clean = prepare_chunk(frame, stats, bbox=bbox)
        if start_ts is not None:
            before = len(clean)
            clean = clean.loc[clean["time"] >= start_ts]
            stats.dropped_outside_time += before - len(clean)
        if end_ts is not None:
            before = len(clean)
            clean = clean.loc[clean["time"] < end_ts]
            stats.dropped_outside_time += before - len(clean)
        if clean.empty:
            continue
        if remaining is not None and len(clean) > remaining:
            clean = clean.iloc[:remaining]
        if remaining is not None:
            remaining -= len(clean)
        stats.rows_written += len(clean)
        _observe(clean, stats)
        main_sink.write(clean)
        if measurement_sink is not None:
            measurement_sink.write(clean)
        hashes.append(
            pd.util.hash_pandas_object(clean.loc[:, list(ROW_KEY)], index=False).to_numpy(
                dtype=np.uint64
            )
        )

    all_hashes = _collect_hashes(hashes)
    if all_hashes.size:
        stats.duplicates_across_chunks = int(all_hashes.size - np.unique(all_hashes).size)
    log.info(
        "%-18s %8s rows  %5.1fs  (%s chunks)",
        spec.name,
        f"{stats.rows_written:,}",
        time.time() - started,
        frames,
    )
    return stats
