"""Canonical schema of the harmonised air-quality dataset.

The dataset is *tidy long*: one row = one (time, place, pollutant, value)
observation or model value.  The six columns requested by the challenge are
first; provenance columns follow.

Everything is in UTC (``time`` is the start of the averaging interval) and
concentrations are in µg/m³.
"""

from __future__ import annotations

import re

import pandas as pd
import pyarrow as pa

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------

#: The six columns that are always present, in the requested order.
CORE_COLUMNS: tuple[str, ...] = (
    "time",
    "lat",
    "lon",
    "altitude_m",
    "pollutant",
    "value",
)

#: Provenance / interpretation columns.  They are what makes the six core
#: columns honest: a value without a source and a "measurement vs model"
#: label is not usable for decisions.
META_COLUMNS: tuple[str, ...] = (
    "unit",
    "source",
    "value_type",
    "station_id",
    "station_name",
    "aggregation",
    "quality",
    "quality_detail",
    "altitude_source",
    "lead_h",
    "issued_utc",
    "station_source_code",
)

ALL_COLUMNS: tuple[str, ...] = CORE_COLUMNS + META_COLUMNS

#: Minimal Arrow schema used when only CORE_COLUMNS are requested.
CORE_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("time", pa.timestamp("ms", tz="UTC")),
        pa.field("lat", pa.float64()),
        pa.field("lon", pa.float64()),
        pa.field("altitude_m", pa.float32()),
        pa.field("pollutant", pa.string()),
        pa.field("value", pa.float32()),
    ]
)

#: Full Arrow schema of the dataset.
SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("time", pa.timestamp("ms", tz="UTC")),
        pa.field("lat", pa.float64()),
        pa.field("lon", pa.float64()),
        pa.field("altitude_m", pa.float32()),
        pa.field("pollutant", pa.string()),
        pa.field("value", pa.float32()),
        pa.field("unit", pa.string()),
        pa.field("source", pa.string()),
        pa.field("value_type", pa.string()),
        pa.field("station_id", pa.string()),
        pa.field("station_name", pa.string()),
        pa.field("aggregation", pa.string()),
        pa.field("quality", pa.string()),
        pa.field("quality_detail", pa.string()),
        pa.field("altitude_source", pa.string()),
        pa.field("lead_h", pa.int16()),
        pa.field("issued_utc", pa.timestamp("ms", tz="UTC")),
        pa.field("station_source_code", pa.string()),
    ]
)

# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

MEASUREMENT = "measurement"
MODEL = "model"
ESTIMATE = "estimate"

VALUE_TYPES: tuple[str, ...] = (MEASUREMENT, MODEL, ESTIMATE)

#: Human-readable explanation used in docs and the manifest.
VALUE_TYPE_LABELS = {
    MEASUREMENT: "Direct observation (official station or citizen sensor).",
    MODEL: "Model output (regional/local dispersion or chemistry-transport model).",
    ESTIMATE: "Derived value (calibrated low-cost sensor, not a direct observation).",
}

# ---------------------------------------------------------------------------
# Pollutants
# ---------------------------------------------------------------------------

#: Canonical lower-case pollutant codes used in the dataset.
POLLUTANTS: tuple[str, ...] = (
    "pm10",
    "pm25",
    "pm1",
    "no2",
    "nox",
    "o3",
    "so2",
    "co",
    "dust",
    "benzene",
)

POLLUTANT_LABELS = {
    "pm10": "PM10 (particles < 10 µm)",
    "pm25": "PM2.5 (particles < 2.5 µm)",
    "pm1": "PM1 (particles < 1 µm)",
    "no2": "NO2 (nitrogen dioxide)",
    "nox": "NOx (nitrogen oxides)",
    "o3": "O3 (ozone)",
    "so2": "SO2 (sulphur dioxide)",
    "co": "CO (carbon monoxide)",
    "dust": "Desert dust (model component)",
    "benzene": "Benzene (C6H6)",
}

_RAW_ALIASES = {
    "pm10": "pm10",
    "pm25": "pm25",
    "pm2.5": "pm25",
    "pm2_5": "pm25",
    "pm1": "pm1",
    "pm1.0": "pm1",
    "no2": "no2",
    "nitrogen_dioxide": "no2",
    "nitrogendioxide": "no2",
    "nox": "nox",
    "o3": "o3",
    "ozone": "o3",
    "so2": "so2",
    "sulphur_dioxide": "so2",
    "sulfur_dioxide": "so2",
    "sulphurdioxide": "so2",
    "co": "co",
    "carbon_monoxide": "co",
    "carbonmonoxide": "co",
    "dust": "dust",
    "benzene": "benzene",
    "benzen": "benzene",
}


def _norm_key(name: object) -> str:
    return re.sub(r"[\s_.\-]+", "_", str(name).strip().lower())


#: Public alias map (normalised key -> canonical code).
POLLUTANT_ALIASES: dict[str, str] = dict(_RAW_ALIASES)


def canonical_pollutant(name: object) -> str:
    """Return the canonical pollutant code for *name* (raises on unknown)."""
    key = _norm_key(name)
    if key in POLLUTANT_ALIASES:
        return POLLUTANT_ALIASES[key]
    compact = key.replace("_", "")
    if compact in POLLUTANT_ALIASES:
        return POLLUTANT_ALIASES[compact]
    raise ValueError(f"Unknown pollutant: {name!r}")


def canonical_pollutant_series(series: pd.Series) -> pd.Series:
    """Vectorised, forgiving canonicalisation (unknown names are kept lower-case)."""
    return series.map(_canonical_or_self).astype("object")


def _canonical_or_self(name: object) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    try:
        return canonical_pollutant(name)
    except ValueError:
        return _norm_key(name)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

UNIT_UG_M3 = "µg/m³"
DEFAULT_UNIT = UNIT_UG_M3

# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------

#: Uniqueness key of the full dataset.  Model forecasts for the same valid
#: time but a different lead/issue time are legitimately distinct rows.
ROW_KEY: tuple[str, ...] = (
    "source",
    "station_id",
    "pollutant",
    "time",
    "aggregation",
    "lead_h",
    "issued_utc",
)

#: Uniqueness key of the de-duplicated measurement-only view.
PRIMARY_KEY: tuple[str, ...] = (
    "station_id",
    "time",
    "pollutant",
    "aggregation",
)
