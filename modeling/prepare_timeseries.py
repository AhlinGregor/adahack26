#!/usr/bin/env python
"""Turn the tidy dataset into regular hourly series for Granite TimeSeries.

Input : data/processed/lj_air_dataset/lj_air_primary.parquet
Output: data/model_input/series_hourly.parquet  (time, station_id, pollutant, value, ...)
        data/model_input/series_summary.csv

The primary view already de-duplicates measurements per station/time/pollutant,
so one time stamp maps to one value.  We reindex each series onto a complete
hourly grid (missing hours stay NaN) because TTM consumes fixed windows with
observed-value masks.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from airdata.paths import MODELING_DIR, find_data_root

log = logging.getLogger("prepare")

DEFAULT_INPUT = MODELING_DIR / "data" / "processed" / "lj_air_dataset" / "lj_air_primary.parquet"
DEFAULT_OUT = MODELING_DIR / "data" / "model_input"
DEFAULT_POLLUTANTS = ("pm10", "pm25")
META_COLUMNS = ("station_name", "lat", "lon", "altitude_m")
CLIP_NEGATIVE = True


def load_primary(path: Path, pollutants: list[str], start: str | None, end: str | None) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the dataset first:\n  python -m airdata build"
        )
    df = pd.read_parquet(
        path,
        columns=["time", "station_id", "station_name", "lat", "lon", "altitude_m", "pollutant", "value", "aggregation", "quality"],
    )
    df = df[(df["aggregation"] == "hour") & df["pollutant"].isin(pollutants)]
    if start:
        df = df[df["time"] >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df["time"] < pd.Timestamp(end, tz="UTC")]
    if df.empty:
        raise ValueError("No hourly measurement rows for the selected pollutants/window")
    return df.sort_values(["station_id", "pollutant", "time"])


def build_series(
    df: pd.DataFrame, min_hours: int, official_only: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    summary: list[dict] = []

    for (station_id, pollutant), group in df.groupby(["station_id", "pollutant"], sort=True):
        # PA_/SC_ are low-cost citizen sensors: useful, but not reference data.
        is_citizen = str(station_id).startswith(("PA_", "SC_"))
        if official_only and is_citizen:
            log.info("skip %-10s %-5s (citizen sensor; use --include-citizen-sensors)", station_id, pollutant)
            continue
        group = group.drop_duplicates(subset="time", keep="last").set_index("time")
        values = pd.to_numeric(group["value"], errors="coerce")
        negative = int((values < 0).sum())
        if CLIP_NEGATIVE:
            values = values.mask(values < 0)
        index = pd.date_range(
            values.index.min().floor("h"), values.index.max().ceil("h"), freq="h", tz="UTC"
        )
        series = values.reindex(index)
        if series.notna().sum() < min_hours:
            log.info("skip %-10s %-5s (%s observed hours)", station_id, pollutant, int(series.notna().sum()))
            continue

        meta = group.iloc[-1]
        frame = pd.DataFrame(
            {
                "time": series.index,
                "station_id": station_id,
                "station_name": meta.get("station_name"),
                "pollutant": pollutant,
                "value": series.to_numpy(dtype="float32"),
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
                "altitude_m": meta.get("altitude_m"),
            }
        )
        frames.append(frame)
        summary.append(
            {
                "station_id": station_id,
                "station_name": meta.get("station_name"),
                "pollutant": pollutant,
                "hours": len(series),
                "observed_hours": int(series.notna().sum()),
                "coverage_pct": round(100 * series.notna().mean(), 1),
                "first": series.index.min().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last": series.index.max().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "mean": round(float(series.mean(skipna=True)), 2),
                "p95": round(float(series.quantile(0.95)), 2),
                "negative_values_masked": negative,
            }
        )

    if not frames:
        raise ValueError("No series passed the minimum-observed-hours filter")
    return pd.concat(frames, ignore_index=True), pd.DataFrame(summary).sort_values(
        ["pollutant", "station_id"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--pollutants", default=",".join(DEFAULT_POLLUTANTS))
    parser.add_argument("--min-hours", type=int, default=20_000)
    parser.add_argument(
        "--include-citizen-sensors",
        action="store_true",
        help="Also include uncalibrated PA_/SC_ low-cost sensors (default: official stations only).",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pollutants = [p.strip().lower() for p in args.pollutants.split(",") if p.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_primary(Path(args.input), pollutants, args.start, args.end)
    series, summary = build_series(df, args.min_hours, official_only=not args.include_citizen_sensors)

    series_path = out_dir / "series_hourly.parquet"
    summary_path = out_dir / "series_summary.csv"
    series["is_official"] = ~series["station_id"].astype(str).str.startswith(("PA_", "SC_"))
    series.to_parquet(series_path, index=False)
    summary.to_csv(summary_path, index=False)

    print(f"\nseries: {len(summary)} station x pollutant, {len(series):,} hourly rows")
    print(summary.to_string(index=False))
    print(f"\nwritten: {series_path}")
    print(f"written: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
