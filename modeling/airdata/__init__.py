"""Harmonised air-quality dataset pipeline for the ADA Hack 2026 data package.

Quick start::

    python -m airdata build --root . --out data/processed/lj_air_dataset

The output is a tidy-long table: one row per time, location, pollutant and
value, with provenance columns saying whether the value is a measurement, a
model or an estimate.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .build import BuildResult, build_dataset  # noqa: E402
from .schema import ALL_COLUMNS, CORE_COLUMNS  # noqa: E402

__all__ = ["BuildResult", "build_dataset", "ALL_COLUMNS", "CORE_COLUMNS", "__version__"]
