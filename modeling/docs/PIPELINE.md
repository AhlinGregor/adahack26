# Dataset pipeline (`airdata`)

Turns the 47 files of the ADA Hack 2026 "Zrak, ki ga dihamo" package into one
tidy-long dataset:

| time | lat | lon | altitude_m | pollutant | value | …provenance… |
|---|---|---|---|---|---|---|

One row = one value of one pollutant at one place and time. All times are UTC,
all concentrations are µg/m³.

## Folder layout

```
modeling/
├── airdata/               # the pipeline package
│   ├── sources/           # one module per input source
│   ├── altitude.py        # station metadata + 30 m DEM fallback
│   ├── stations.py        # unified station registry (ARSO ↔ EEA ↔ sensors)
│   ├── validation.py      # per-chunk cleaning + counters
│   ├── build.py           # orchestration, primary view, manifest
│   ├── cli.py             # python -m airdata ...
│   └── docs.py            # generates data_dictionary.md into the output
├── data/                  # generated (git-ignored)
│   ├── processed/lj_air_dataset/
│   │   ├── lj_air.parquet          # full dataset, ~10.7M rows
│   │   ├── lj_air_primary.parquet  # de-duplicated measurements, ~2.0M rows
│   │   ├── stations.csv
│   │   ├── manifest.json           # per-source counts, drops, coverage
│   │   ├── data_dictionary.md
│   │   └── README.md
│   └── model_input/       # hourly series for Granite (see train_granite.py)
├── prepare_timeseries.py
├── train_granite.py
├── forecast.py
├── build_dataset.py
├── tests/
└── docs/
```

The data package itself is one level up (`../01_meritve`, `../02_modeli`, …).
`airdata.paths.find_data_root()` walks up from the working directory, so the
pipeline works both from `modeling/` and from the repository root.

## Quick start

```bash
cd modeling
python -m venv .venv && . .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

python -m airdata build            # full build, ~1 minute, 10.7M rows
python -m airdata verify           # invariant checks on the built file
python -m airdata inspect          # per-source summary
```

The dataset output defaults to `modeling/data/processed/lj_air_dataset`
(always inside `modeling/`).

## Sources

| Source | Type | What is included | Rows |
|---|---|---|---:|
| `arso_pm` | measurement | ARSO hourly PM10/PM2.5, LJ Bežigrad, Celovška, Vič (2016–2026, incl. Nov 2026 continuation) | 352k |
| `arso_live` | measurement | ARSO live XML feed, 13–21 Nov 2026, 25 stations, 8 pollutants | 14k |
| `eea` | measurement | EEA validated hourly/daily values 2013–2025 + 2026 up-to-date stream, 13 stations | 1.42M |
| `purpleair` | measurement | PurpleAir PA-II, 3 devices, PM1/PM2.5/PM10 (factory ATM) | 224k |
| `sensor_community` | measurement | Sensor.Community SDS011, 9 outdoor devices, PM10/PM2.5 | 159k |
| `sensor_calibrated` | estimate | The package's calibrated citizen-sensor PM values | 277k |
| `cams` | model | CAMS Europe 0.1°, PM10/PM2.5/NO2/O3/SO2/CO/dust, 8 points | 5.19M |
| `cams_forecast` | model | CAMS forecast issued 13 Nov 2026 (4 days) | 8k |
| `camx` | model | ARSO CAMx 4.4 km, PM2.5/PM10/O3 in station cells, 2023–2026 (lead 1–24) | 2.81M |
| `gral` | model | ARSO GRAL 15 m PM10 contributions (small combustion, personal cars), 2021 | 245k |

Not included on purpose: the CAMS `european_aqi` column (an index, not a
pollutant), the EEA `pollen`-type parameters (none here), CAMx NetCDF grids
(point values only — grids stay in `02_modeli/camx`), GRAL rasters, and the
weather/inversion tables (they are not air concentrations; they are better
joined by `time` and `station` after loading).

## Column reference

The six requested columns come first, then provenance:

* `time` – UTC start of the averaging interval
* `lat`, `lon` – WGS84 of the station/sensor, or of the model cell for CAMS
* `altitude_m` – station metadata, else 30 m Copernicus DEM, else nearest station
* `pollutant` – canonical code (`pm10`, `pm25`, `pm1`, `no2`, `nox`, `o3`,
  `so2`, `co`, `benzene`, `dust`)
* `value` – µg/m³ (CO from the ARSO live feed converted from mg/m³)
* `unit`, `source`, `value_type` – provenance and **measurement / model / estimate**
* `station_id`, `station_name` – unified id (ARSO code, EEA code, `PA_<id>`, `SC_<id>`)
* `aggregation` – `hour`, `day` or the EEA `var` aggregate
* `quality`, `quality_detail` – `ok`, `below_detection`, `unverified`,
  `channel_disagreement`, `sensor_fault`, `negative`
* `altitude_source` – `station_metadata`, `eea_metadata`, `cams_cell`,
  `dem_30m`, `nearest_station`
* `lead_h`, `issued_utc` – forecast lead / issue time (CAMx, CAMS forecast)
* `station_source_code` – the source's own identifier (e.g. `SI0003A`)

## Design decisions

**Unified station ids.** EEA reports `SI0003A` where ARSO says `E403`. The
registry reads `eea_postaje.geojson` (it carries `arso_code`), so both collapse
to `E403` and the `lj_air_primary` view can de-duplicate them.

**A primary view.** `lj_air_primary.parquet` contains measurements only and
exactly one value per `(station_id, time, pollutant, aggregation)`. The
priority is: ARSO direct > ARSO live > EEA > PurpleAir > Sensor.Community. The
full file keeps every source (and every model), so nothing is lost.

**Units.** Everything is µg/m³. The ARSO live feed publishes CO in mg/m³; it is
multiplied by 1000. No other conversion is applied, and no value is clipped.
The few negative values (instrument noise) are kept and flagged.

**Altitudes.** ARSO/EEA/PurpleAir values come with the station altitude. CAMS
rows use the model-cell elevation. Sensor.Community and GRAL points have no
altitude, so the 30 m Copernicus DEM is sampled (`dem_30m`); outside the DEM
the nearest station altitude is used (`nearest_station`).

**Two model caveats are encoded in the data, not in a footnote.** CAMx rows
carry `lead_h` (1–24 = same-day forecast, 25–48 = tomorrow; the latter only
with `--include-camx-tomorrow`) and `issued_utc`. GRAL rows carry
`source=gral_kurisca|gral_promet` and a `quality_detail` saying the value is a
single-source contribution, and that the traffic run is only relative.

**CAMS coordinates.** For CAMS the `lat`/`lon`/`altitude_m` describe the model
cell (`model_lat`, `model_lon`, `model_elev_m`); `station_id` keeps the
requested point. This keeps "where does this value apply" honest.

**No spatial filter by default.** The ARSO live feed and CAMx contain stations
across Slovenia; the build counts rows outside the basin bbox in the manifest
but keeps them. Use `--bbox min_lat,min_lon,max_lat,max_lon` to filter.

## CLI

```
python -m airdata build [--root ..] [--out DIR]
                        [--sources all|measurements|models|estimates|arso_pm,eea,...]
                        [--exclude camx,gral] [--start ISO] [--end ISO]
                        [--bbox ...] [--format parquet,csv] [--core-only]
                        [--no-primary] [--include-camx-tomorrow]
                        [--limit N] [--chunk-size N] [--dem PATH]
python -m airdata list-sources
python -m airdata inspect [--path DIR]
python -m airdata verify  [--path DIR]
```

`--core-only` writes exactly the six requested columns (no primary view).
`--limit N` caps rows per source and is meant for quick tests.

## Validation

Every chunk is checked for: parseable UTC time, non-null coordinates inside
global bounds, finite numeric value, known pollutant, and duplicates on the
dataset key. Drops are counted per source and reported in `manifest.json`.
At the end of each source, the row-key hashes of all chunks are compared to
detect cross-chunk duplicates. `python -m airdata verify` re-checks the written
file (nulls, ranges, poll codes, duplicates per source).

Current build: **0 duplicates**, 10,701,175 rows, 2,033,997 primary rows,
altitude coverage 100 %.

## Adding a source

1. Create `airdata/sources/my_source.py` with a `read(task)` generator that
   yields canonical frames (use `add_provenance` from `sources/base.py`).
2. Define a `SourceSpec(name=..., value_type=..., priority=..., reader=read)`.
   `priority=None` keeps it out of the primary view; measurements that should
   appear there get 1–5.
3. Register it in `airdata/sources/__init__.py` (`ALL_SPECS`).

The reader only has to produce `time`, `lat`, `lon`, `pollutant`, `value` and
whatever provenance it knows; `prepare_chunk` and the altitude resolver fill
the rest.

## Attribution

ARSO (measurements, CAMx, GRAL, live feed), EEA (Air Quality e-Reporting),
PurpleAir, Sensor.Community (ODbL), Open-Meteo / CAMS (CC BY 4.0), Copernicus
DEM. The generated `data_dictionary.md` repeats the per-source attribution.
