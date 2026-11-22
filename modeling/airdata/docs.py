"""Documentation generated next to the dataset."""

from __future__ import annotations

from pathlib import Path

from .schema import (
    ALL_COLUMNS,
    CORE_COLUMNS,
    POLLUTANT_LABELS,
    VALUE_TYPE_LABELS,
)

COLUMN_DOCS: dict[str, tuple[str, str]] = {
    "time": ("UTC timestamp", "Start of the averaging interval (ISO-8601, UTC)."),
    "lat": ("degrees", "WGS84 latitude the value applies to (station, sensor or model cell)."),
    "lon": ("degrees", "WGS84 longitude the value applies to."),
    "altitude_m": ("m a.s.l.", "Altitude of the station/point (or of the model cell for CAMS)."),
    "pollutant": ("code", "Canonical pollutant code, see the pollutant table."),
    "value": ("µg/m³", "Concentration (or modelled contribution) in micrograms per cubic metre."),
    "unit": ("text", "Always µg/m³ in this dataset; CO from the ARSO live feed was converted from mg/m³."),
    "source": ("code", "Input source, see the source table."),
    "value_type": ("code", "measurement | model | estimate."),
    "station_id": ("code", "Unified station/point id (ARSO code, EEA code, PA_<id>, SC_<id>)."),
    "station_name": ("text", "Human-readable station/point name."),
    "aggregation": ("code", "hour | day | var (the EEA 'var' rows are irregular aggregates)."),
    "quality": ("code", "Short data-quality flag, see the quality table."),
    "quality_detail": ("text", "Free-form explanation of the quality flag / source caveat."),
    "altitude_source": ("code", "station_metadata | eea_metadata | cams_cell | dem_30m | nearest_station | unknown."),
    "lead_h": ("hours", "CAMx forecast lead time (1-24 same-day, 25-48 tomorrow); empty otherwise."),
    "issued_utc": ("UTC timestamp", "Issue/run time of a forecast (CAMS forecast, CAMx); empty for observations."),
    "station_source_code": ("code", "The identifier used by the original source (e.g. E403, SI0003A, 96479)."),
}

QUALITY_DOCS = {
    "ok": "Usable value.",
    "below_detection": "Below the detection limit; stored as limit/2 (or as reported when the source does that).",
    "unverified": "Real-time / not yet validated value (EEA validity 4).",
    "invalid": "Invalid or maintenance value; normally dropped because the value is empty.",
    "channel_disagreement": "PurpleAir PM2.5 channels A and B differ by more than 50%.",
    "sensor_fault": "Sensor.Community flag set by the data package (e.g. broken device).",
    "negative": "Negative measured value kept as reported (instrument noise).",
}

ATTRIBUTION = {
    "arso_pm": "Vir: ARSO, Sektor za kakovost zraka.",
    "arso_live": "Vir: ARSO (urni XML feed).",
    "eea": "Vir: EEA / ARSO (Air Quality e-Reporting).",
    "purpleair": "Vir: PurpleAir (podatki lastnikov naprav).",
    "sensor_community": "Vir: Sensor.Community (sensor.community), ODbL.",
    "sensor_calibrated": "Vir: izračun paketa (umerjanje na ARSO); ocena, ne meritev.",
    "cams": "Vir: Open-Meteo.com / CAMS (Copernicus), CC BY 4.0.",
    "cams_forecast": "Vir: Open-Meteo.com / CAMS (Copernicus), CC BY 4.0.",
    "camx": "Vir: ARSO, model CAMx 4,4 km.",
    "camx_tomorrow": "Vir: ARSO, model CAMx 4,4 km (napoved za jutri).",
    "gral": "Vir: ARSO, model GRAL 15 m.",
}


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    return str(value)


def write_documentation(out_dir: Path, *, manifest: dict, specs) -> None:
    """Write ``data_dictionary.md`` and a short ``README.md`` into the output dir."""
    lines: list[str] = []
    add = lines.append

    add("# Ljubljana air-quality dataset (tidy long)")
    add("")
    add(
        "One row = one value of one pollutant at one place and time. "
        "Times are UTC, concentrations are µg/m³."
    )
    add("")
    add(f"Generated: {manifest['generated_at']}  ")
    add(f"Rows: **{manifest['dataset']['rows']:,}**  ")
    if manifest["primary_view"]["rows"] is not None:
        add(f"Primary (de-duplicated measurements): **{manifest['primary_view']['rows']:,}** rows")
    add("")

    add("## Core columns")
    add("")
    add("| Column | Unit | Meaning |")
    add("|---|---|---|")
    for column in CORE_COLUMNS:
        unit, meaning = COLUMN_DOCS[column]
        add(f"| `{column}` | {unit} | {meaning} |")
    add("")
    add("## Provenance columns")
    add("")
    add("| Column | Unit | Meaning |")
    add("|---|---|---|")
    for column in ALL_COLUMNS:
        if column in CORE_COLUMNS:
            continue
        unit, meaning = COLUMN_DOCS[column]
        add(f"| `{column}` | {unit} | {meaning} |")
    add("")
    add(
        "`value_type` is the key honesty column: **measurement** = observed, "
        "**model** = modelled, **estimate** = derived. Never compare a model "
        "value with a measurement as if they were the same quantity."
    )
    add("")

    add("## Pollutants")
    add("")
    add("| Code | Meaning |")
    add("|---|---|")
    for code, label in POLLUTANT_LABELS.items():
        add(f"| `{code}` | {label} |")
    add("")

    add("## Quality flags")
    add("")
    add("| Flag | Meaning |")
    add("|---|---|")
    for code, meaning in QUALITY_DOCS.items():
        add(f"| `{code}` | {meaning} |")
    add("")

    add("## Sources in this build")
    add("")
    add("| Source | Type | Rows | Time range | Pollutants | Stations | Attribution |")
    add("|---|---|---:|---|---|---:|---|")
    for name, stats in manifest["sources"].items():
        add(
            "| `{}` | {} | {} | {} → {} | {} | {} | {} |".format(
                name,
                stats["value_type"],
                f"{stats['rows_written']:,}",
                _fmt(stats["time_min"]),
                _fmt(stats["time_max"]),
                ", ".join(stats["pollutants"]) or "-",
                stats["stations"],
                ATTRIBUTION.get(name, "-"),
            )
        )
    add("")

    add("## Known caveats")
    add("")
    add(
        "- **Different sources for the same station/time/pollutant exist** "
        "(e.g. ARSO and EEA for E403/SI0003A). Use `lj_air_primary.parquet` for one "
        "measurement per station/time/pollutant/aggregation, or filter by `source`."
    )
    add(
        "- **Citizen sensors are not reference measurements.** PurpleAir and "
        "Sensor.Community values are uncalibrated (the calibrated variant is "
        "`sensor_calibrated`, value_type=`estimate`). The package README reports "
        "that Ljubljana citizen sensors underestimate official values in winter "
        "(ratio 0.6-0.9)."
    )
    add(
        "- **CAMS** is a ~10 km model; all three Ljubljana stations fall in the "
        "same cell. Rows use the *model cell* coordinates (`model_lat`/`model_lon`/"
        "`model_elev_m` of the package) so `lat`/`lon`/`altitude_m` describe where "
        "the value applies, and `station_id` keeps the requested point."
    )
    add(
        "- **CAMx** values are the 4.4 km cell containing the station. "
        "`lead_h` 1-24 is the same-day forecast (ARSO's best reconstruction for the "
        "past), 25-48 is the forecast for tomorrow and is only available if the "
        "build used `--include-camx-tomorrow`. Always filter by `lead_h` before "
        "mixing rows for the same `time`."
    )
    add(
        "- **GRAL** rows are *contributions of one source category* (small "
        "combustion or personal cars), not total PM10, and the traffic run is only "
        "relative (absolute values at least 10x too high). This is encoded in "
        "`source` and `quality_detail`."
    )
    add(
        "- **Negative values** (mostly NO2/O3 and a few PM10) are instrument noise "
        "below the detection limit; they are kept as reported and flagged, not "
        "silently clipped."
    )
    add(
        "- **Altitude** is station metadata where available, else the 30 m "
        "Copernicus DEM (sensor sites) or the nearest known station. See "
        "`altitude_source`."
    )
    add(
        "- **Sort order** is by source, then by the source's own time order. The "
        "file is not globally sorted by time; sort after loading if you need it."
    )
    add("")

    add("## Reading")
    add("")
    add("```python")
    add("import pandas as pd")
    add("")
    add(f"df = pd.read_parquet('{manifest['dataset']['file']}')")
    add("pm = df[(df.value_type == 'measurement') & (df.pollutant == 'pm25')]")
    add("winter = pm[pm.time.dt.month.isin([11, 12, 1, 2])]")
    add("print(winter.groupby('station_name').value.mean().sort_values())")
    add("")
    add("primary = pd.read_parquet('%s')" % (manifest["primary_view"]["file"] or ""))
    add("```")
    add("")

    add("## Column dtypes")
    add("")
    add("| Column | Arrow type |")
    add("|---|---|")
    from .schema import SCHEMA

    for field in SCHEMA:
        add(f"| `{field.name}` | `{field.type}` |")
    add("")

    (out_dir / "data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")

    readme = [
        "# Built dataset",
        "",
        f"Built at {manifest['generated_at']} from `{manifest['root']}`.",
        "",
        "| File | Contents |",
        "|---|---|",
        f"| `{Path(manifest['dataset']['file']).name}` | Full tidy long dataset, {manifest['dataset']['rows']:,} rows |",
    ]
    if manifest["primary_view"]["rows"] is not None:
        readme.append(
            f"| `{Path(manifest['primary_view']['file']).name}` | De-duplicated measurements, "
            f"{manifest['primary_view']['rows']:,} rows |"
        )
    readme += [
        "| `stations.csv` | Station registry with coordinates, altitude and external codes |",
        "| `manifest.json` | Build parameters, per-source row counts/drops/coverage |",
        "| `data_dictionary.md` | Column, pollutant, quality and source documentation |",
        "",
        "See `data_dictionary.md` for caveats. Measurements, models and estimates "
        "are distinguished by the `value_type` column and must not be mixed "
        "without saying so.",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")
