#!/usr/bin/env python
"""Evaluation report and figures for the fine-tuned Granite forecaster.

Reads ``artifacts/granite-ttm-lj/{metrics.json,predictions_test.parquet}`` and
writes:

* ``metrics_summary.md``  – tables for the pitch / README
* ``episode_example.png`` – a real 24 h forecast vs observation
* ``skill_by_lead.png``   – MAE by lead hour, model / persistence / spatial IDW
* updated ``metrics.json`` with the high-pollution and spatial subsets
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from airdata.paths import MODELING_DIR
from spatial import haversine_matrix

DEFAULT_ARTIFACT = MODELING_DIR / "artifacts" / "granite-ttm-lj"
HIGH_POLLUTION_DAY = 25.0
LEAD_GROUPS = {"1_12": (1, 12), "13_24": (13, 24), "1_24": (1, 24)}
MAX_KM = 60.0


def metrics_for(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {}
    y = frame["y_true"].to_numpy(dtype="float64")
    pred = frame["y_pred"].to_numpy(dtype="float64")
    err = pred - y
    mae = float(np.mean(np.abs(err)))
    out = {
        "model_mae": round(mae, 3),
        "model_rmse": round(float(np.sqrt(np.mean(err**2))), 3),
        "n": int(len(frame)),
    }
    if "persistence" in frame.columns:
        p_mae = float(np.mean(np.abs(frame["persistence"].to_numpy(dtype="float64") - y)))
        out["persistence_mae"] = round(p_mae, 3)
        out["skill_vs_persistence"] = round(1 - mae / p_mae, 4) if p_mae else None
    return out


def spatial_idw(predictions: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-out IDW of neighbouring station forecasts at the same lead."""
    rows: list[dict] = []
    for (pollutant, forecast_time, lead), group in predictions.groupby(
        ["pollutant", "forecast_time", "lead_h"], sort=True
    ):
        if len(group) < 2:
            continue
        lats = group["lat"].to_numpy(dtype=float)
        lons = group["lon"].to_numpy(dtype=float)
        values = group["y_pred"].to_numpy(dtype=float)
        distances = haversine_matrix(lats, lons)
        weights = 1.0 / (distances + 1.0) ** 2
        weights[distances > MAX_KM] = 0.0
        np.fill_diagonal(weights, 0.0)
        denominator = weights.sum(axis=1)
        blended = np.divide(
            (values[None, :] * weights).sum(axis=1),
            denominator,
            out=np.full(len(group), np.nan),
            where=denominator > 0,
        )
        for i, (_, row) in enumerate(group.iterrows()):
            if math.isnan(blended[i]):
                continue
            rows.append(
                {
                    "station_id": row["station_id"],
                    "pollutant": pollutant,
                    "forecast_time": forecast_time,
                    "target_time": row["target_time"],
                    "lead_h": lead,
                    "y_true": row["y_true"],
                    "y_pred_idw": blended[i],
                }
            )
    return pd.DataFrame(rows)


def subset_metrics(predictions: pd.DataFrame, mask: pd.Series, column: str = "y_pred") -> dict:
    out = {}
    for label, (first, last) in LEAD_GROUPS.items():
        sub = predictions[mask & predictions["lead_h"].between(first, last)]
        if sub.empty:
            continue
        out[label] = metrics_for(sub.rename(columns={column: "y_pred"}))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    args = parser.parse_args(argv)

    out = Path(args.artifact)
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    predictions = pd.read_parquet(out / "predictions_test.parquet")
    predictions["target_time"] = pd.to_datetime(predictions["target_time"], utc=True)
    predictions["forecast_time"] = pd.to_datetime(predictions["forecast_time"], utc=True)
    predictions["day"] = predictions["target_time"].dt.floor("D")
    predictions["day_mean"] = predictions.groupby(["station_id", "pollutant", "day"])["y_true"].transform("mean")

    high = predictions["day_mean"] >= HIGH_POLLUTION_DAY
    metrics["test"]["high_pollution_days"] = subset_metrics(predictions, high)

    idw = spatial_idw(predictions)
    metrics["test"]["spatial_idw"] = {}
    if not idw.empty:
        metrics["test"]["spatial_idw"] = subset_metrics(idw, pd.Series(True, index=idw.index), column="y_pred_idw")
        # per-lead errors for the figure
        idw_lead = idw.assign(abs_err=(idw["y_pred_idw"] - idw["y_true"]).abs()).groupby("lead_h")["abs_err"].mean()
    else:
        idw_lead = pd.Series(dtype=float)

    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # --- example episode ---------------------------------------------------
    station, pollutant = "E403", "pm25"
    candidate = predictions[
        (predictions["station_id"] == station) & (predictions["pollutant"] == pollutant)
    ]
    if candidate.empty:
        station = predictions["station_id"].iloc[0]
        pollutant = predictions["pollutant"].iloc[0]
        candidate = predictions[(predictions["station_id"] == station) & (predictions["pollutant"] == pollutant)]
    daily_mean = candidate.groupby("forecast_time")["y_true"].mean()
    worst_start = daily_mean.idxmax()
    episode = candidate[candidate["forecast_time"] == worst_start].sort_values("lead_h")

    lead_profile = predictions.assign(abs_err=(predictions["y_pred"] - predictions["y_true"]).abs()).groupby("lead_h")["abs_err"].mean()
    persistence_profile = predictions.assign(abs_err=(predictions["persistence"] - predictions["y_true"]).abs()).groupby("lead_h")["abs_err"].mean()

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    ax = axes[0]
    ax.plot(episode["target_time"], episode["y_true"], color="#1f3b4d", lw=2, label="measured")
    ax.plot(episode["target_time"], episode["y_pred"], color="#d1495b", lw=2, label="Granite TTM 24 h forecast")
    ax.plot(episode["target_time"], episode["persistence"], color="#8d99ae", lw=1.4, ls="--", label="persistence")
    ax.set_title(f"{station} PM2.5 – 24 h forecast from {worst_start:%d %b %Y %H:%M} UTC")
    ax.set_ylabel("µg/m³")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.25)

    ax = axes[1]
    ax.plot(lead_profile.index, lead_profile.values, color="#d1495b", lw=2, label="Granite TTM")
    ax.plot(persistence_profile.index, persistence_profile.values, color="#8d99ae", lw=1.6, ls="--", label="persistence")
    if not idw_lead.empty:
        ax.plot(idw_lead.index, idw_lead.values, color="#2a9d8f", lw=1.6, label="IDW of neighbours (spatial)")
    ax.set_title("Mean absolute error by lead hour (test period)")
    ax.set_xlabel("lead hour")
    ax.set_ylabel("MAE (µg/m³)")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(out / "episode_example.png", dpi=150)
    plt.close(fig)

    # --- markdown ----------------------------------------------------------
    test = metrics["test"]["overall"]
    zero = (metrics.get("zero_shot_test") or {}).get("overall", {})
    high = metrics["test"]["high_pollution_days"]
    idw_metrics = metrics["test"]["spatial_idw"]

    def row(label: str, values: dict) -> str:
        if not values:
            return f"| {label} | – | – | – |"
        return (
            f"| {label} | {values['model_mae']:.2f} | {values['model_rmse']:.2f} | "
            f"{values['skill_vs_persistence'] * 100:+.1f} % |"
        )

    lines = [
        "# Granite TTM – evaluation summary",
        "",
        f"Base model: `{metrics['base_model']}`  ",
        f"Test period: {metrics['splits']['test'][0]} – {metrics['splits']['test'][1]}  ",
        f"Horizon: {metrics['config']['horizon']} h",
        "",
        "## All test windows",
        "",
        "| Horizon | Granite TTM MAE | RMSE | Zero-shot MAE | Persistence MAE | Skill |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, human in (("1_12", "1–12 h"), ("13_24", "13–24 h"), ("1_24", "1–24 h")):
        t = test.get(label)
        z = zero.get(label)
        if not t:
            continue
        lines.append(
            f"| {human} | {t['model_mae']:.2f} | {t['model_rmse']:.2f} | "
            f"{(z or {}).get('model_mae', float('nan')):.2f} | {t['persistence_mae']:.2f} | "
            f"{t['skill_vs_persistence'] * 100:+.1f} % |"
        )

    lines += [
        "",
        "## High-pollution days (observed daily mean > 25 µg/m³)",
        "",
        "| Horizon | MAE | RMSE | Persistence MAE | Skill |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, human in (("1_12", "1–12 h"), ("1_24", "1–24 h")):
        t = high.get(label)
        if not t:
            continue
        lines.append(
            f"| {human} | {t['model_mae']:.2f} | {t['model_rmse']:.2f} | "
            f"{t['persistence_mae']:.2f} | {t['skill_vs_persistence'] * 100:+.1f} % |"
        )

    lines += [
        "",
        "## Spatial layer: predicting a station from its neighbours (leave-one-out IDW)",
        "",
        "| Horizon | Station model MAE | IDW of neighbours MAE |",
        "|---|---:|---:|",
    ]
    for label, human in (("1_12", "1–12 h"), ("1_24", "1–24 h")):
        station_m = test.get(label, {}).get("model_mae")
        idw_m = idw_metrics.get(label, {}).get("model_mae")
        if station_m is None or idw_m is None:
            continue
        lines.append(f"| {human} | {station_m:.2f} | {idw_m:.2f} |")

    lines += [
        "",
        "## By series (24 h, test period)",
        "",
        "| Station | Pollutant | MAE 1–12 h | MAE 1–24 h | Persistence 1–24 h | Skill 1–24 h | n |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    per_series = {(row["station_id"], row["pollutant"], row["lead_group"]): row for row in metrics["test"]["per_series"]}
    keys = sorted({(row["station_id"], row["pollutant"]) for row in metrics["test"]["per_series"]})
    for station_id, pollutant_name in keys:
        short = per_series.get((station_id, pollutant_name, "1_12"))
        full = per_series.get((station_id, pollutant_name, "1_24"))
        if not full:
            continue
        lines.append(
            f"| {station_id} | {pollutant_name} | "
            f"{short['model_mae'] if short else float('nan'):.2f} | {full['model_mae']:.2f} | "
            f"{full['persistence_mae']:.2f} | {full['skill_vs_persistence'] * 100:+.1f} % | {full['n']} |"
        )

    lines += [
        "",
        "![Episode example](episode_example.png)",
        "",
        "The left panel is the 24 h forecast window with the highest measured daily mean",
        "in the test period. The right panel shows error by lead hour, including the",
        "spatial IDW layer that predicts a station from its neighbours' forecasts.",
        "",
    ]
    (out / "metrics_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"figure: {out / 'episode_example.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
