"""EEA/ARSO Air Quality e-Reporting: validated and up-to-date values.

The files are already in long form (one row per station x pollutant x time):
hourly values 2013-2025, the up-to-date 2026 stream, and daily gravimetric
PM means 2013-2025.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from ..schema import MEASUREMENT, canonical_pollutant_series
from .base import SourceSpec, Task, add_provenance, parse_utc

log = logging.getLogger(__name__)

NAME = "eea"

HOURLY_FILES = (
    Path("01_meritve") / "eea_si_validirano_urno_2013_2019.csv.gz",
    Path("01_meritve") / "eea_si_validirano_urno_2020_2025.csv.gz",
    Path("01_meritve") / "eea_si_utd_2026.csv",
)
DAILY_FILES = (Path("01_meritve") / "eea_si_validirano_dnevno_2013_2025.csv",)

USECOLS = [
    "time_utc",
    "station_code",
    "station_name",
    "lat",
    "lon",
    "pollutant",
    "aggregation",
    "value",
    "validity",
    "verification",
]


def _quality(validity: pd.Series, verification: pd.Series) -> tuple[pd.Series, pd.Series]:
    validity = pd.to_numeric(validity, errors="coerce")
    verification = pd.to_numeric(verification, errors="coerce")
    quality = np.select(
        [validity == 1, validity.isin([2, 3]), validity == 4],
        ["ok", "below_detection", "unverified"],
        default="invalid",
    )
    detail = "validity=" + validity.astype("Int64").astype(str) + ";verification=" + verification.astype("Int64").astype(str)
    detail = detail.where(pd.notna(validity), None)
    return pd.Series(quality, index=validity.index, dtype="object"), pd.Series(detail, dtype="object")


def _prepare(chunk: pd.DataFrame, task: Task, aggregation: str) -> pd.DataFrame:
    chunk = chunk.copy()
    chunk["time"] = parse_utc(chunk["time_utc"])
    chunk["station_source_code"] = chunk["station_code"].astype("string")
    chunk["station_id"] = chunk["station_source_code"].map(task.registry.by_eea)
    chunk["pollutant"] = canonical_pollutant_series(chunk["pollutant"])

    altitude = chunk["station_id"].map(task.registry.altitude)
    chunk["altitude_m"] = pd.to_numeric(altitude, errors="coerce")
    chunk["altitude_source"] = np.where(chunk["altitude_m"].notna(), "eea_metadata", None)

    chunk["quality"], chunk["quality_detail"] = _quality(chunk["validity"], chunk["verification"])
    chunk["aggregation"] = aggregation

    return chunk.loc[
        :,
        [
            "time",
            "lat",
            "lon",
            "altitude_m",
            "altitude_source",
            "pollutant",
            "value",
            "station_id",
            "station_name",
            "station_source_code",
            "quality",
            "quality_detail",
            "aggregation",
        ],
    ]


def _iter_files(files, task: Task, aggregation: str) -> Iterator[pd.DataFrame]:
    for rel in files:
        path = task.root / rel
        if not path.exists():
            log.warning("missing input %s", path)
            continue
        for chunk in pd.read_csv(
            path,
            chunksize=task.chunk_size,
            usecols=lambda c: c in USECOLS,
            low_memory=False,
        ):
            yield _prepare(chunk, task, aggregation)


def read(task: Task):
    for frame in _iter_files(HOURLY_FILES, task, "hour"):
        yield add_provenance(frame, source=NAME, value_type=MEASUREMENT, aggregation="hour")
    for frame in _iter_files(DAILY_FILES, task, "day"):
        yield add_provenance(frame, source=NAME, value_type=MEASUREMENT, aggregation="day")


SPEC = SourceSpec(
    name=NAME,
    value_type=MEASUREMENT,
    priority=3,
    description="EEA validated hourly/daily values (2013-2025) and 2026 up-to-date stream, 13 stations.",
    reader=read,
)
