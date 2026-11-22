#!/usr/bin/env python
"""Forecast with the fine-tuned IBM Granite TimeSeries model – by station or by coordinate.

    python forecast.py --station E403 --pollutant pm25
    python forecast.py --lat 46.0516 --lon 14.5059 --pollutant pm25 --k 3

In coordinate mode the forecast is an inverse-distance blend of the k nearest
station forecasts; the per-station contributions and distances are printed and
returned in the ``stations`` column.  The output is a model forecast, not a
measurement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from airdata.paths import MODELING_DIR
from spatial import idw_weights
from tsfm_public import TinyTimeMixerForPrediction

DEFAULT_SERIES = MODELING_DIR / "data" / "model_input" / "series_hourly.parquet"
DEFAULT_MODEL = MODELING_DIR / "artifacts" / "granite-ttm-lj" / "model"
FREQ_TOKEN = 7  # hourly


def load_station_series(path: Path, pollutant: str) -> dict[str, dict]:
    df = pd.read_parquet(path)
    df = df[df["pollutant"] == pollutant].sort_values(["station_id", "time"])
    out: dict[str, dict] = {}
    for station, group in df.groupby("station_id"):
        out[str(station)] = {
            "index": pd.DatetimeIndex(group["time"]),
            "values": group["value"].to_numpy(dtype=np.float32),
            "lat": float(group["lat"].iloc[0]),
            "lon": float(group["lon"].iloc[0]),
            "name": str(group["station_name"].iloc[0]),
        }
    return out


def forecast_series(
    model: TinyTimeMixerForPrediction,
    index: pd.DatetimeIndex,
    values: np.ndarray,
    start: pd.Timestamp,
    context: int,
    horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    position = int(np.searchsorted(index.astype("int64"), start.value))
    if position < context:
        raise ValueError(f"Not enough history before {start} ({position} hours, need {context})")
    past = values[position - context : position]
    mask = (~np.isnan(past)).astype("float32")
    with torch.no_grad():
        output = model(
            past_values=torch.from_numpy(np.nan_to_num(past, nan=0.0)[None, :, None]),
            past_observed_mask=torch.from_numpy(mask[None, :, None]),
            freq_token=torch.tensor([FREQ_TOKEN], dtype=torch.long),
        )
    forecast = output.prediction_outputs.detach().cpu().numpy()[0, :horizon, 0]
    return forecast, past


def default_start(series: dict) -> pd.Timestamp:
    latest = max(s["index"].max() for s in series.values())
    return latest.ceil("h") + pd.Timedelta(hours=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", default=None, help="Station id, e.g. E403.")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--pollutant", default="pm25")
    parser.add_argument("--time", default=None, help="Forecast start (UTC ISO); default: after the last observation.")
    parser.add_argument("--context", type=int, default=512)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--k", type=int, default=3, help="Nearest stations blended in coordinate mode.")
    parser.add_argument("--max-km", type=float, default=60.0)
    parser.add_argument("--series", default=str(DEFAULT_SERIES))
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--out", default=None)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)

    if args.station is None and (args.lat is None or args.lon is None):
        raise SystemExit("Give --station, or --lat and --lon")

    torch.set_num_threads(args.threads)
    series = load_station_series(Path(args.series), args.pollutant)
    if not series:
        raise SystemExit(f"No series for pollutant {args.pollutant}")

    model = TinyTimeMixerForPrediction.from_pretrained(args.model)
    model.eval()

    start = pd.Timestamp(args.time, tz="UTC") if args.time else default_start(series)
    start = start.floor("h")

    if args.station is not None:
        if args.station not in series:
            raise SystemExit(f"Unknown station {args.station}; available: {', '.join(sorted(series))}")
        s = series[args.station]
        forecast, _ = forecast_series(model, s["index"], s["values"], start, args.context, args.horizon)
        target_times = pd.date_range(start, periods=len(forecast), freq="h", tz="UTC")
        result = pd.DataFrame(
            {
                "target_time": target_times.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lead_h": np.arange(1, len(forecast) + 1),
                "station_id": args.station,
                "lat": s["lat"],
                "lon": s["lon"],
                "pollutant": args.pollutant,
                "forecast_ug_m3": np.round(forecast, 2),
                "horizon_group": np.where(np.arange(1, len(forecast) + 1) <= 12, "1_12h", "13_24h"),
                "stations": args.station,
                "model": "ibm-granite/granite-timeseries-ttm-r2 fine-tuned",
                "value_type": "model",
            }
        )
        print(f"{args.station} / {args.pollutant}: forecast from {start} ({s['name']}, {s['lat']:.4f}, {s['lon']:.4f})")
        print(result.head(6).to_string(index=False))
        print("...")
        print(
            f"first 12 h: mean {forecast[:12].mean():.1f}, max {forecast[:12].max():.1f} µg/m³; "
            f"13-24 h: mean {forecast[12:24].mean():.1f}, max {forecast[12:24].max():.1f} µg/m³"
        )
    else:
        weights = idw_weights(
            list(series), {k: (v["lat"], v["lon"]) for k, v in series.items()},
            args.lat, args.lon, k=args.k, max_km=args.max_km,
        )
        if not weights:
            raise SystemExit("No station within --max-km of the requested point")
        forecasts = []
        used = []
        for station, distance, weight in weights:
            s = series[station]
            # Keep the blend honest: ignore stations whose data stop before the
            # forecast start (otherwise we would silently forecast stale data).
            if s["index"].max() < start - pd.Timedelta(hours=2):
                print(f"skip {station}: last observation {s['index'].max()} is too old for {start}")
                continue
            forecast, _ = forecast_series(model, s["index"], s["values"], start, args.context, args.horizon)
            forecasts.append(forecast * weight)
            used.append((station, distance, weight))
        if not used:
            raise SystemExit("All candidate stations have stale data for the requested time")
        total_weight = sum(w for _, _, w in used)
        blended = sum(forecasts) / total_weight
        target_times = pd.date_range(start, periods=len(blended), freq="h", tz="UTC")
        station_label = "; ".join(f"{s} ({d:.1f} km, {w / total_weight:.0%})" for s, d, w in used)
        result = pd.DataFrame(
            {
                "target_time": target_times.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lead_h": np.arange(1, len(blended) + 1),
                "station_id": "IDW",
                "lat": args.lat,
                "lon": args.lon,
                "pollutant": args.pollutant,
                "forecast_ug_m3": np.round(blended, 2),
                "horizon_group": np.where(np.arange(1, len(blended) + 1) <= 12, "1_12h", "13_24h"),
                "stations": station_label,
                "model": "ibm-granite/granite-timeseries-ttm-r2 fine-tuned + IDW",
                "value_type": "model",
            }
        )
        print(f"Point ({args.lat:.4f}, {args.lon:.4f}) / {args.pollutant}: forecast from {start}")
        print("blend: " + station_label)
        print(result.head(6).to_string(index=False))
        print("...")
        print(
            f"first 12 h: mean {blended[:12].mean():.1f}, max {blended[:12].max():.1f} µg/m³; "
            f"13-24 h: mean {blended[12:24].mean():.1f}, max {blended[12:24].max():.1f} µg/m³"
        )

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() == ".json":
            out.write_text(result.to_json(orient="records", indent=2), encoding="utf-8")
        else:
            result.to_csv(out, index=False)
        print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
