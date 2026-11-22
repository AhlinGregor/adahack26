"""ARSO GRAL 15 m: modelled PM10 contribution of small combustion and traffic.

GRAL values are *contributions of a single source category*, not total
concentrations, and the traffic run is only relative (absolute values are at
least 10x too high).  Both caveats are encoded in ``source`` and
``quality_detail``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..schema import MODEL
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "gral"
FILES = {
    "gral_kurisca": Path("02_modeli") / "gral" / "gral_kurisca_tocke_urno.csv",
    "gral_promet": Path("02_modeli") / "gral" / "gral_promet_tocke_urno.csv",
}
CAVEATS = {
    "gral_kurisca": "GRAL small-combustion contribution only (no background, traffic or industry)",
    "gral_promet": "GRAL personal-car contribution only; ABSOLUTE VALUES ARE RELATIVE (>=10x too high)",
}

USECOLS = ["time_utc", "point_id", "pm10_prispevek", "name", "lat", "lon"]


def _read_one(path: Path, source: str, task: Task):
    if not path.exists():
        log.warning("missing input %s", path)
        return None
    df = pd.read_csv(path, usecols=lambda c: c in USECOLS)
    if df.empty:
        return None
    df = df.copy()
    df["time"] = parse_utc(df["time_utc"])
    df["station_id"] = df["point_id"]
    df["station_source_code"] = df["point_id"]
    df["station_name"] = df["name"]
    df["altitude_m"] = None
    df["altitude_source"] = None
    df["quality"] = "ok"
    df["quality_detail"] = CAVEATS[source]
    df["pollutant"] = "pm10"
    df["value"] = df["pm10_prispevek"]
    return df.loc[
        :,
        [
            "time",
            "station_id",
            "station_name",
            "station_source_code",
            "lat",
            "lon",
            "altitude_m",
            "altitude_source",
            "pollutant",
            "value",
            "quality",
            "quality_detail",
        ],
    ]


def read(task: Task):
    for source, rel in FILES.items():
        frame = _read_one(task.root / rel, source, task)
        if frame is None:
            continue
        yield add_provenance(frame, source=source, value_type=MODEL, aggregation="hour")


SPEC = SourceSpec(
    name=NAME,
    value_type=MODEL,
    priority=None,
    description="ARSO GRAL 15 m modelled PM10 contribution (small combustion and traffic), hours of 2021.",
    reader=read,
)
