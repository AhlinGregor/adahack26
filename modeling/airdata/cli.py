"""Command line interface: ``python -m airdata ...``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .build import build_dataset
from .paths import default_output_dir, find_data_root
from .schema import ALL_COLUMNS, CORE_COLUMNS, POLLUTANTS, ROW_KEY, SCHEMA
from .sources import ALL_SPECS, GROUPS

log = logging.getLogger("airdata")

DEFAULT_OUT = default_output_dir()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _cmd_build(args: argparse.Namespace) -> int:
    result = build_dataset(
        root=args.root,
        out=args.out,
        sources=args.sources,
        exclude=args.exclude,
        chunk_size=args.chunk_size,
        include_camx_tomorrow=args.include_camx_tomorrow,
        start=args.start,
        end=args.end,
        bbox=args.bbox,
        formats=args.format,
        core_only=args.core_only,
        include_primary=not args.no_primary,
        limit=args.limit,
        dem=args.dem,
    )
    print("\n" + result.summary())
    print(f"manifest: {result.out_dir / 'manifest.json'}")
    checks = result.manifest["checks"]
    print(
        "checks  : duplicates={} outside_basin={} negative={} altitude_missing={}".format(
            "none" if checks["all_sources_unique_on_row_key"] else "FOUND",
            checks["rows_outside_basin_bbox"],
            checks["negative_values_kept"],
            checks["altitude_missing"],
        )
    )
    if not checks["all_sources_unique_on_row_key"]:
        log.error("Duplicate rows found on the dataset key - inspect manifest.json")
        return 1
    return 0


# ---------------------------------------------------------------------------
# inspect / list / verify
# ---------------------------------------------------------------------------


def _cmd_list_sources(_: argparse.Namespace) -> int:
    print(f"{'source':<18} {'type':<12} {'primary':<8} description")
    print("-" * 110)
    for spec in ALL_SPECS:
        print(
            f"{spec.name:<18} {spec.value_type:<12} "
            f"{('yes' if spec.in_primary_view else 'no'):<8} {spec.description}"
        )
    print("\ngroups: " + ", ".join(f"{k} ({len(v)})" for k, v in GROUPS.items()))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.is_dir():
        manifest_path = path / "manifest.json"
        parquet_path = path / "lj_air.parquet"
    else:
        manifest_path = path.parent / "manifest.json"
        parquet_path = path
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"dataset : {manifest['dataset']['file']}")
        print(f"rows    : {manifest['dataset']['rows']:,}")
        print(f"built   : {manifest['generated_at']}")
        print(f"primary : {manifest['primary_view']['rows']}")
        print("\nper source:")
        for name, stats in manifest["sources"].items():
            print(
                f"  {name:<18} {stats['rows_written']:>10,} rows  "
                f"{stats['time_min']} -> {stats['time_max']}  "
                f"{stats['value_type']}"
            )
        return 0
    if not parquet_path.exists():
        log.error("No dataset at %s", path)
        return 1
    pf = pq.ParquetFile(parquet_path)
    print(f"file    : {parquet_path}")
    print(f"rows    : {pf.metadata.num_rows:,}")
    print(f"columns : {', '.join(pf.schema_arrow.names)}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if path.is_dir():
        path = path / "lj_air.parquet"
    if not path.exists():
        log.error("No dataset at %s", path)
        return 1

    pf = pq.ParquetFile(path)
    missing_schema = [f.name for f in SCHEMA if f.name not in pf.schema_arrow.names]
    if missing_schema and not args.core:
        log.error("Missing columns: %s", missing_schema)
        return 1

    wanted = [c for c in ALL_COLUMNS if c in pf.schema_arrow.names]
    hashes: dict[str, list[np.ndarray]] = {}
    problems: list[str] = []
    rows = 0
    for batch in pf.iter_batches(batch_size=args.batch_size, columns=wanted):
        df = batch.to_pandas()
        rows += len(df)
        if df["time"].isna().any():
            problems.append("null time")
        if df["value"].isna().any():
            problems.append("null value")
        if df["lat"].isna().any() or df["lon"].isna().any():
            problems.append("null coordinates")
        if (~df["lat"].between(-90, 90)).any() or (~df["lon"].between(-180, 180)).any():
            problems.append("coordinates out of range")
        if (~df["value"].between(-100, 100_000)).any():
            problems.append("implausible value")
        if df["altitude_m"].notna().any() and (~df["altitude_m"].dropna().between(-50, 9000)).any():
            problems.append("altitude out of range")
        unknown = sorted(set(df["pollutant"].dropna()) - set(POLLUTANTS))
        if unknown:
            problems.append(f"unknown pollutants {unknown}")
        if "source" in df.columns:
            key = df.loc[:, [c for c in ROW_KEY if c in df.columns]]
            by_source = df.groupby("source", observed=True).size()
            for source in by_source.index:
                subset = key.loc[df["source"] == source]
                hashes.setdefault(str(source), []).append(
                    pd.util.hash_pandas_object(subset, index=False).to_numpy(dtype=np.uint64)
                )

    duplicate_sources = []
    for source, chunks in hashes.items():
        values = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.uint64)
        if values.size and np.unique(values).size != values.size:
            duplicate_sources.append(source)

    print(f"file    : {path}")
    print(f"rows    : {rows:,}")
    print(f"columns : {len(pf.schema_arrow.names)}")
    print(f"duplicates on key per source: {'FOUND in ' + ', '.join(duplicate_sources) if duplicate_sources else 'none'}")
    if problems:
        unique = sorted(set(problems))
        print("problems: " + "; ".join(unique))
        return 1
    print("checks  : OK (no nulls in key columns, coordinates/values in range, no duplicates)")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airdata",
        description="Build and inspect the harmonised Ljubljana air-quality dataset.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="Build the dataset from the data package.")
    b.add_argument(
        "--root",
        default=None,
        help="Root of the data package (default: auto-detected from the cwd).",
    )
    b.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory (default: modeling/data/...).")
    b.add_argument(
        "--sources",
        default="all",
        help="Comma-separated sources or a group (all, measurements, models, estimates).",
    )
    b.add_argument("--exclude", default=None, help="Comma-separated sources to skip.")
    b.add_argument("--chunk-size", type=int, default=250_000, help="Rows per processed chunk.")
    b.add_argument("--include-camx-tomorrow", action="store_true", help="Also keep CAMx lead hours 25-48.")
    b.add_argument("--start", default=None, help="Keep rows with time >= START (UTC ISO).")
    b.add_argument("--end", default=None, help="Keep rows with time < END (UTC ISO).")
    b.add_argument("--bbox", default=None, help="Filter min_lat,min_lon,max_lat,max_lon.")
    b.add_argument("--format", default="parquet", help="Output format(s): parquet,csv (default: parquet).")
    b.add_argument("--core-only", action="store_true", help="Write only the six core columns.")
    b.add_argument("--no-primary", action="store_true", help="Skip the de-duplicated measurement view.")
    b.add_argument("--limit", type=int, default=None, help="Max rows per source (for quick tests).")
    b.add_argument("--dem", default=None, help="Override the DEM GeoTIFF used for sensor altitudes.")
    b.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR.")
    b.set_defaults(func=_cmd_build)

    ls = sub.add_parser("list-sources", help="List available sources.")
    ls.set_defaults(func=_cmd_list_sources)

    ins = sub.add_parser("inspect", help="Summarise a built dataset or manifest.")
    ins.add_argument("--path", default=str(DEFAULT_OUT))
    ins.set_defaults(func=_cmd_inspect)

    ver = sub.add_parser("verify", help="Check invariants of a built dataset.")
    ver.add_argument("--path", default=str(DEFAULT_OUT))
    ver.add_argument("--batch-size", type=int, default=500_000)
    ver.add_argument("--core", action="store_true", help="Allow a core-only (6 column) dataset.")
    ver.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "log_level", "INFO"))
    try:
        return int(args.func(args))
    except (ValueError, FileNotFoundError) as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
