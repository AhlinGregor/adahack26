#!/usr/bin/env python
"""Fine-tune IBM Granite TimeSeries (TTM r2) on Ljubljana air-quality series.

The base model is ``ibm-granite/granite-timeseries-ttm-r2`` (TinyTimeMixer,
Apache-2.0), IBM's time-series foundation model.  It is fine-tuned on hourly
PM10/PM2.5 measured in and around the Ljubljana basin.

Design choices in this version
------------------------------
* **Forecast horizon 24 h** (the model's 512-48 checkpoint is filtered to 24);
  results are reported for the first 12 h, hours 13-24, and the full 24 h.
* **Location is kept explicit**: every prediction carries the station's
  lat/lon, and the coordinate-aware IDW layer in `forecast.py` blends the
  nearest station forecasts for an arbitrary point.
* The test set is the **last N days** of data (default 14), the validation set
  the N days before it; both are relative to the freshest observation.

Usage
-----
    python prepare_timeseries.py
    python train_granite.py

Outputs (``artifacts/granite-ttm-lj/``):
    model/  metrics.json  predictions_test.parquet  training_log.csv  run_config.json
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from transformers import set_seed

from airdata.paths import MODELING_DIR
from tsfm_public import get_model

log = logging.getLogger("train")

BASE_MODEL = "ibm-granite/granite-timeseries-ttm-r2"
DEFAULT_SERIES = MODELING_DIR / "data" / "model_input" / "series_hourly.parquet"
DEFAULT_OUT = MODELING_DIR / "artifacts" / "granite-ttm-lj"

FREQ_TOKEN = 7  # hourly, per TSFM DEFAULT_FREQUENCY_MAPPING
LEAD_GROUPS = {"1_12": (1, 12), "13_24": (13, 24), "1_24": (1, 24)}


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


@dataclass
class Window:
    key: tuple[str, str]
    position: int  # index of the first forecast hour


class HourlySeries:
    """Regular hourly series with NaN gaps and the station coordinates."""

    def __init__(self, frame: pd.DataFrame) -> None:
        frame = frame.sort_values("time")
        self.index = pd.DatetimeIndex(frame["time"])
        self.values = frame["value"].to_numpy(dtype=np.float32)
        self.station_name = str(frame["station_name"].iloc[0])
        self.lat = float(frame["lat"].iloc[0])
        self.lon = float(frame["lon"].iloc[0])

    def __len__(self) -> int:
        return len(self.values)


def load_series(path: Path, pollutants: list[str] | None) -> dict[tuple[str, str], HourlySeries]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run prepare_timeseries.py first.")
    df = pd.read_parquet(path)
    if pollutants:
        df = df[df["pollutant"].isin(pollutants)]
    if df.empty:
        raise ValueError("No series selected")

    series: dict[tuple[str, str], HourlySeries] = {}
    for (station_id, pollutant), group in df.groupby(["station_id", "pollutant"]):
        series[(str(station_id), str(pollutant))] = HourlySeries(group)
    return series


def make_windows(
    series: dict[tuple[str, str], HourlySeries],
    *,
    context: int,
    horizon: int,
    stride: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    min_past_observed: float = 0.5,
    min_future_observed: float = 0.5,
) -> list[Window]:
    windows: list[Window] = []
    for key, s in series.items():
        n = len(s)
        pos = context
        while pos + horizon <= n:
            first = s.index[pos]
            last = s.index[pos + horizon - 1]
            if first >= start and last < end:
                past = s.values[pos - context : pos]
                future = s.values[pos : pos + horizon]
                if (
                    np.mean(~np.isnan(past)) >= min_past_observed
                    and np.mean(~np.isnan(future)) >= min_future_observed
                ):
                    windows.append(Window(key, pos))
            pos += stride
    return windows


def _last_observed(values: np.ndarray, position: int, lookback: int = 24 * 7) -> float:
    lo = max(0, position - lookback)
    window = values[lo:position]
    observed = window[~np.isnan(window)]
    return float(observed[-1]) if observed.size else math.nan


class ForecastWindows(Dataset):
    def __init__(
        self,
        series: dict[tuple[str, str], HourlySeries],
        windows: list[Window],
        context: int,
        horizon: int,
    ) -> None:
        self.series = series
        self.windows = windows
        self.context = context
        self.horizon = horizon

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, item: int) -> dict[str, torch.Tensor]:
        window = self.windows[item]
        values = self.series[window.key].values
        past = values[window.position - self.context : window.position]
        future = values[window.position : window.position + self.horizon]
        past_mask = ~np.isnan(past)
        future_mask = ~np.isnan(future)
        return {
            "past_values": torch.from_numpy(np.nan_to_num(past, nan=0.0)[:, None]),
            "past_observed_mask": torch.from_numpy(past_mask.astype(np.float32)[:, None]),
            "future_values": torch.from_numpy(np.nan_to_num(future, nan=0.0)[:, None]),
            "future_observed_mask": torch.from_numpy(future_mask.astype(np.float32)[:, None]),
            "freq_token": torch.tensor(FREQ_TOKEN, dtype=torch.long),
        }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


@torch.no_grad()
def evaluate(
    model: torch.nn.Module,
    dataset: ForecastWindows,
    *,
    batch_size: int,
    collect_predictions: bool = False,
    max_batches: int | None = None,
) -> tuple[dict, pd.DataFrame | None]:
    model.eval()
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    records: list[dict] = []
    buckets: dict[tuple[str, str, str], dict[str, float]] = {}

    for batch_index, batch in enumerate(loader):
        if max_batches is not None and batch_index >= max_batches:
            break
        output = model(**batch)
        predictions = output.prediction_outputs.detach().cpu().numpy()[:, :, 0]
        truths = batch["future_values"].numpy()[:, :, 0]
        masks = batch["future_observed_mask"].numpy()[:, :, 0] > 0
        offset = batch_index * batch_size

        for row in range(predictions.shape[0]):
            window = dataset.windows[offset + row]
            series = dataset.series[window.key]
            persistence, daily = baseline_predictions(series, window.position, predictions.shape[1])
            for label, (first_lead, last_lead) in LEAD_GROUPS.items():
                sl = slice(first_lead - 1, last_lead)
                pred = predictions[row, sl]
                true = truths[row, sl]
                mask = masks[row, sl]
                n = int(mask.sum())
                if not n:
                    continue
                bucket = buckets.setdefault(
                    (window.key[0], window.key[1], label),
                    {"n": 0.0, "abs": 0.0, "sq": 0.0, "p_abs": 0.0, "d_abs": 0.0},
                )
                errors = pred[mask] - true[mask]
                bucket["n"] += n
                bucket["abs"] += float(np.abs(errors).sum())
                bucket["sq"] += float((errors**2).sum())
                bucket["p_abs"] += float(np.abs(persistence[sl][mask] - true[mask]).sum())
                bucket["d_abs"] += float(np.abs(daily[sl][mask] - true[mask]).sum())

            if collect_predictions:
                times = series.index[window.position : window.position + predictions.shape[1]]
                for j in range(predictions.shape[1]):
                    if not masks[row, j]:
                        continue
                    records.append(
                        {
                            "station_id": window.key[0],
                            "pollutant": window.key[1],
                            "lat": series.lat,
                            "lon": series.lon,
                            "forecast_time": times[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "target_time": times[j].strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "lead_h": j + 1,
                            "y_true": float(truths[row, j]),
                            "y_pred": float(predictions[row, j]),
                            "persistence": float(persistence[j]),
                            "daily_persistence": float(daily[j]),
                        }
                    )

    metrics = _summarise(buckets)
    return metrics, (pd.DataFrame(records) if collect_predictions else None)


def baseline_predictions(s: HourlySeries, position: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    last = _last_observed(s.values, position)
    persistence = np.full(horizon, last, dtype=np.float64)
    daily = np.full(horizon, np.nan, dtype=np.float64)
    for j in range(horizon):
        k = position + j - 24
        if 0 <= k < len(s.values) and not np.isnan(s.values[k]):
            daily[j] = s.values[k]
    daily = np.where(np.isnan(daily), persistence, daily)
    return persistence, daily


def _summarise(buckets: dict[tuple[str, str, str], dict[str, float]]) -> dict:
    overall: dict[str, dict] = {}
    by_pollutant: dict[str, dict[str, dict]] = {}
    per_series: list[dict] = []

    def aggregate(items: list[dict]) -> dict:
        n = sum(b["n"] for b in items)
        if not n:
            return {}
        mae = sum(b["abs"] for b in items) / n
        p_mae = sum(b["p_abs"] for b in items) / n
        return {
            "model_mae": round(mae, 3),
            "model_rmse": round(math.sqrt(sum(b["sq"] for b in items) / n), 3),
            "persistence_mae": round(p_mae, 3),
            "daily_persistence_mae": round(sum(b["d_abs"] for b in items) / n, 3),
            "skill_vs_persistence": round(1 - mae / p_mae, 4) if p_mae else None,
            "n": int(n),
        }

    for label in LEAD_GROUPS:
        items = [b for (_, _, lab), b in buckets.items() if lab == label]
        if items:
            overall[label] = aggregate(items)
        pollutants = {p for (_, p, lab) in buckets if lab == label}
        for pollutant in sorted(pollutants):
            subset = [b for (_, p, lab), b in buckets.items() if p == pollutant and lab == label]
            if subset:
                by_pollutant.setdefault(pollutant, {})[label] = aggregate(subset)

    for (station, pollutant, label), bucket in sorted(buckets.items()):
        if label not in ("1_12", "1_24") or not bucket["n"]:
            continue
        mae = bucket["abs"] / bucket["n"]
        p_mae = bucket["p_abs"] / bucket["n"]
        per_series.append(
            {
                "station_id": station,
                "pollutant": pollutant,
                "lead_group": label,
                "model_mae": round(mae, 3),
                "persistence_mae": round(p_mae, 3),
                "skill_vs_persistence": round(1 - mae / p_mae, 4) if p_mae else None,
                "n": int(bucket["n"]),
            }
        )

    return {"overall": overall, "by_pollutant": by_pollutant, "per_series": per_series}


# ---------------------------------------------------------------------------
# model / training
# ---------------------------------------------------------------------------


def build_model(args):
    return get_model(
        BASE_MODEL,
        context_length=args.context,
        prediction_length=args.horizon,
        freq="h",
        force_return="model",
    )


def train_one_epoch(model, loader, optimizer, *, max_grad_norm: float = 1.0, max_batches: int | None = None) -> float:
    model.train()
    total, count = 0.0, 0
    for batch_index, batch in enumerate(loader):
        if max_batches is not None and batch_index >= max_batches:
            break
        output = model(**batch)
        loss = output.loss
        if loss is None or not torch.isfinite(loss):
            continue
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
        optimizer.step()
        total += float(loss.detach()) * len(batch["past_values"])
        count += len(batch["past_values"])
    return total / max(count, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", default=str(DEFAULT_SERIES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--pollutants", default="pm10,pm25")
    parser.add_argument("--context", type=int, default=512)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--stride", type=int, default=48)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--min-hours", type=int, default=20_000)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--valid-days", type=int, default=60)
    parser.add_argument("--valid-stride", type=int, default=24)
    parser.add_argument("--test-stride", type=int, default=12)
    parser.add_argument("--no-zero-shot", action="store_true")
    parser.add_argument("--eval-batches", type=int, default=None)
    parser.add_argument("--max-train-batches", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    set_seed(args.seed)
    torch.set_num_threads(args.threads)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pollutants = [p.strip().lower() for p in args.pollutants.split(",") if p.strip()]
    series = load_series(Path(args.series), pollutants)
    series = {k: s for k, s in series.items() if np.count_nonzero(~np.isnan(s.values)) >= args.min_hours}
    if not series:
        raise ValueError("No series passed --min-hours")

    latest = max(s.index.max() for s in series.values())
    earliest = min(s.index.min() for s in series.values())
    test_start = latest - pd.Timedelta(days=args.test_days)
    valid_start = test_start - pd.Timedelta(days=args.valid_days)
    boundaries = {
        "train": (earliest, valid_start),
        "valid": (valid_start, test_start),
        "test": (test_start, latest + pd.Timedelta(hours=1)),
    }
    log.info(
        "split: train %s..%s | valid %s..%s | test %s..%s (last %d days)",
        boundaries["train"][0].date(),
        boundaries["train"][1].date(),
        boundaries["valid"][0].date(),
        boundaries["valid"][1].date(),
        boundaries["test"][0].date(),
        boundaries["test"][1].date(),
        args.test_days,
    )

    train_windows = make_windows(
        series, context=args.context, horizon=args.horizon, stride=args.stride,
        start=boundaries["train"][0], end=boundaries["train"][1],
    )
    valid_windows = make_windows(
        series, context=args.context, horizon=args.horizon, stride=args.valid_stride,
        start=boundaries["valid"][0], end=boundaries["valid"][1],
    )
    test_windows = make_windows(
        series, context=args.context, horizon=args.horizon, stride=args.test_stride,
        start=boundaries["test"][0], end=boundaries["test"][1],
    )
    if not train_windows:
        raise ValueError("No training windows - check the series and split dates")

    train_ds = ForecastWindows(series, train_windows, args.context, args.horizon)
    valid_ds = ForecastWindows(series, valid_windows, args.context, args.horizon)
    test_ds = ForecastWindows(series, test_windows, args.context, args.horizon)

    log.info(
        "series=%d  train_windows=%d  valid_windows=%d  test_windows=%d",
        len(series), len(train_windows), len(valid_windows), len(test_windows),
    )

    log.info("loading base model %s", BASE_MODEL)
    model = build_model(args)
    log.info("trainable parameters: %s", f"{sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    log.info("model context=%s prediction=%s", model.config.context_length, model.config.prediction_length)

    zero_shot_metrics = None
    if not args.no_zero_shot and test_windows:
        zero_shot_metrics, _ = evaluate(model, test_ds, batch_size=args.batch_size, max_batches=args.eval_batches)
        log.info("zero-shot test MAE@1_12=%.2f", zero_shot_metrics["overall"]["1_12"]["model_mae"])

    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
    log_rows: list[dict] = []
    best_state = copy.deepcopy(model.state_dict())
    best_val = math.inf
    stale = 0

    for epoch in range(1, args.epochs + 1):
        started = time.time()
        train_loss = train_one_epoch(model, train_loader, optimizer, max_batches=args.max_train_batches)
        if valid_windows:
            val_metrics, _ = evaluate(model, valid_ds, batch_size=args.batch_size, max_batches=args.eval_batches)
            val_mae = val_metrics["overall"]["1_12"]["model_mae"]
        else:
            val_mae = train_loss
        log.info(
            "epoch %2d/%d  train_loss=%.3f  val_MAE@1_12=%.3f  (%.0fs)",
            epoch, args.epochs, train_loss, val_mae, time.time() - started,
        )
        log_rows.append({"epoch": epoch, "train_loss": train_loss, "val_mae_1_12": val_mae, "seconds": round(time.time() - started, 1)})

        if val_mae == val_mae and val_mae < best_val - 1e-4:
            best_val = val_mae
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                log.info("early stopping after %d epochs without improvement", args.patience)
                break

    model.load_state_dict(best_state)
    model.save_pretrained(out_dir / "model")

    valid_metrics, _ = evaluate(model, valid_ds, batch_size=args.batch_size) if valid_windows else (None, None)
    test_metrics, predictions = evaluate(
        model, test_ds, batch_size=args.batch_size, collect_predictions=True
    ) if test_windows else (None, None)

    if predictions is not None:
        predictions.to_parquet(out_dir / "predictions_test.parquet", index=False)
    pd.DataFrame(log_rows).to_csv(out_dir / "training_log.csv", index=False)

    metrics = {
        "base_model": BASE_MODEL,
        "config": {
            "context_length": args.context,
            "prediction_length": args.horizon,
            "horizon": args.horizon,
            "lead_groups": {k: list(v) for k, v in LEAD_GROUPS.items()},
            "batch_size": args.batch_size,
            "epochs": args.epochs,
            "learning_rate": args.lr,
            "weight_decay": args.weight_decay,
            "stride": args.stride,
            "test_days": args.test_days,
            "valid_days": args.valid_days,
            "test_stride": args.test_stride,
            "valid_stride": args.valid_stride,
            "seed": args.seed,
            "pollutants": pollutants,
            "series": sorted({f"{k[0]}:{k[1]}" for k in series}),
        },
        "splits": {name: [str(b[0]), str(b[1])] for name, b in boundaries.items()},
        "windows": {"train": len(train_windows), "valid": len(valid_windows), "test": len(test_windows)},
        "zero_shot_test": zero_shot_metrics,
        "valid": valid_metrics,
        "test": test_metrics,
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out_dir / "run_config.json").write_text(json.dumps(vars(args), indent=2), encoding="utf-8")

    print(f"\n=== results (test: {boundaries['test'][0]} .. {boundaries['test'][1]}, last {args.test_days} days) ===")
    for label in ("1_12", "13_24", "1_24"):
        test = (test_metrics or {}).get("overall", {}).get(label)
        zero = (zero_shot_metrics or {}).get("overall", {}).get(label)
        if not test:
            continue
        print(
            f"{label:<5} fine-tuned MAE={test['model_mae']:.2f}  "
            f"zero-shot MAE={(zero or {}).get('model_mae', float('nan')):.2f}  "
            f"persistence MAE={test['persistence_mae']:.2f}  skill={test['skill_vs_persistence']:+.1%}"
        )
    print(f"\nartifacts: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
