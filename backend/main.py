"""
Air quality API (ARSO + EEA + PurpleAir + Sensor.Community).

Install:  pip install fastapi uvicorn pandas
Run:      uvicorn api:app --reload        (or: python api.py)
Docs:     http://127.0.0.1:8000/docs      (interactive, you can try the queries there)

Set the data folder with the DATA_DIR environment variable (default: 01_meritve).
The first start builds the table from the CSV files and caches it in obs_cache.pkl.
Delete that file to rebuild after the data changes.
"""
import json
import os
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

DATA = Path(os.environ.get("DATA_DIR", "01_meritve"))
CACHE = Path("obs_cache.pkl")
MAX_ROWS = 500_000                       # protection against huge queries
COLS = ["time_utc", "source", "station_id", "name", "lat", "lon", "pollutant", "value"]
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


MAX_ROWS = 500_000                 # normal format
MAX_ROWS_COMPACT = 5_000_000       # compact format
# ----------------------------------------------------------------------------
# 1. Build one long table: time, source, station, location, pollutant, value
# ----------------------------------------------------------------------------
def read(f, **kw):
    return pd.read_csv(DATA / f, parse_dates=["time_utc"], low_memory=False, **kw)


def melt_pm(df, source, cols):
    out = df.melt(id_vars=["time_utc", "station_id", "name", "lat", "lon"],
                  value_vars=list(cols), var_name="pollutant", value_name="value")
    out["pollutant"] = out["pollutant"].map(cols)
    out["source"] = source
    return out[COLS]


def build_obs():
    # ARSO
    arso = pd.concat([read("arso_lj_pm_urno_2016_2026.csv.gz"),
                      read("arso_lj_pm_urno_2026_11_dopolnitev.csv")])
    arso = arso.drop_duplicates(["time_utc", "station_code"], keep="last")
    arso = arso.rename(columns={"station_code": "station_id", "station_name": "name"})
    parts = [melt_pm(arso, "ARSO", {"pm25": "PM2.5", "pm10": "PM10"})]

    # PurpleAir
    pa = read("purpleair_lj_urno.csv").rename(columns={"sensor_index": "station_id"})
    parts.append(melt_pm(pa, "PurpleAir", {"pm25_atm": "PM2.5", "pm10_atm": "PM10"}))

    # Sensor.Community (without flagged faults)
    sc = read("sensor_community_lj_urno_2023_2026.csv", dtype={"flag": str})
    sc = sc[sc["flag"].isna()].copy()
    sc["station_id"] = sc["sensor_id"]
    sc["name"] = "Sensor.Community " + sc["sensor_id"].astype(str)
    parts.append(melt_pm(sc, "Sensor.Community", {"pm25": "PM2.5", "pm10": "PM10"}))

    # EEA (hourly only; no PM for the 3 stations that ARSO already covers)
    eea = pd.concat([read(f) for f in ["eea_si_validirano_urno_2013_2019.csv.gz",
                                       "eea_si_validirano_urno_2020_2025.csv.gz",
                                       "eea_si_utd_2026.csv"]])
    eea = eea[eea.aggregation == "hour"]
    eea = eea[~(eea.station_code.isin(["SI0003A", "SI0072A", "SI0075A"])
                & eea.pollutant.isin(["PM10", "PM2.5"]))]
    eea = eea.rename(columns={"station_code": "station_id", "station_name": "name"})
    eea["source"] = "EEA"
    parts.append(eea[COLS])

    # Calibrated citizen sensors (estimates, not measurements) as separate sources
    if (DATA / "senzorji_umerjeno_urno.csv.gz").exists():
        cal = read("senzorji_umerjeno_urno.csv.gz", dtype={"pm25_cal_note": str})
        cal = cal[cal["pm25_cal_note"].isna()].copy()
        cal["station_id"] = cal["sensor_id"]
        cal["name"] = cal["source"] + " " + cal["station_id"].astype(str)
        cal["source"] = cal["source"] + " (umerjeno)"
        cal["pollutant"] = "PM2.5"
        cal["value"] = cal["pm25_cal"]
        parts.append(cal[COLS])

    obs = pd.concat(parts, ignore_index=True).dropna(subset=["value"])
    obs["station_id"] = obs["station_id"].astype(str)
    obs["value"] = obs["value"].clip(lower=0)
    obs = obs.drop_duplicates(["time_utc", "source", "station_id", "pollutant"])
    return obs.sort_values("time_utc").reset_index(drop=True)


def load_obs():
    if CACHE.exists():
        return pd.read_pickle(CACHE)
    obs = build_obs()
    obs.to_pickle(CACHE)
    return obs


# ----------------------------------------------------------------------------
# 2. Station details from the geojson files
# ----------------------------------------------------------------------------
GEOJSON = {  # source: (file, property holding the station id)
    "ARSO": ("arso_lj_postaje.geojson", "station_code"),
    "EEA": ("eea_postaje.geojson", "station_code"),
    "PurpleAir": ("purpleair_lj_naprave.geojson", "sensor_index"),
    "Sensor.Community": ("sensor_community_lj_naprave.geojson", "sensor_id"),
}


def load_details():
    out = {}
    for src, (fname, id_prop) in GEOJSON.items():
        path = DATA / fname
        if not path.exists():
            continue
        for ft in json.load(open(path, encoding="utf-8"))["features"]:
            props = ft["properties"]
            out[(src, str(props[id_prop]))] = props
    return out


OBS = load_obs()
DETAILS = load_details()
BY_POLLUTANT = {p: g.set_index("time_utc").sort_index() for p, g in OBS.groupby("pollutant")}


def build_stations():
    meta = OBS.groupby(["source", "station_id"]).agg(
        name=("name", "first"), lat=("lat", "median"), lon=("lon", "median")).reset_index()
    cov = OBS.groupby(["source", "station_id", "pollutant"]).agg(
        first=("time_utc", "min"), last=("time_utc", "max"), n=("value", "size")).reset_index()
    stations = {}
    for m in meta.to_dict("records"):
        c = cov[(cov.source == m["source"]) & (cov.station_id == m["station_id"])]
        base_source = m["source"].replace(" (umerjeno)", "")
        stations[(m["source"], m["station_id"])] = {
            "source": m["source"],
            "station_id": m["station_id"],
            "name": m["name"],
            "lat": float(m["lat"]),
            "lon": float(m["lon"]),
            "pollutants": sorted(c.pollutant.unique().tolist()),
            "details": DETAILS.get((base_source, m["station_id"]), {}),
            "coverage": [{"pollutant": r.pollutant,
                          "from": r.first.strftime(TIME_FMT),
                          "to": r.last.strftime(TIME_FMT),
                          "n_hours": int(r.n)} for r in c.itertuples()],
        }
    return stations


STATIONS = build_stations()

# ----------------------------------------------------------------------------
# 3. The API
# ----------------------------------------------------------------------------
app = FastAPI(title="Air quality API", description="PM2.5, PM10, NO2 and O3 stations in the Ljubljana basin. "
              "Times are UTC; values are in µg/m³.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

Pollutant = Literal["PM2.5", "PM10", "NO2", "O3"]

def parse_time(s: str, end_of_day: bool = False) -> pd.Timestamp:
    try:
        t = pd.Timestamp(s)
    except Exception:
        raise HTTPException(400, f"Cannot parse time '{s}'. Use e.g. 2026-01-15 or 2026-01-15T20:00 (UTC).")
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    if end_of_day and len(s.strip()) <= 10:          # a date without a time means the whole day
        t += pd.Timedelta(hours=23)
    return t


@app.get("/")
def root():
    return {"endpoints": ["/stations", "/readings", "/docs"],
            "sources": sorted({s["source"] for s in STATIONS.values()}),
            "pollutants": sorted(BY_POLLUTANT)}


@app.get("/stations")
def stations(source: Optional[str] = None, pollutant: Optional[Pollutant] = None):
    """All stations with location, details and what data each has. Optional filters."""
    out = list(STATIONS.values())
    if source:
        out = [s for s in out if s["source"] == source]
    if pollutant:
        out = [s for s in out if pollutant in s["pollutants"]]
    return {"count": len(out), "stations": out}

@app.get("/readings")
def readings(pollutant: Pollutant,
             start: str,
             end: Optional[str] = None,
             source: Optional[str] = None,
             station_id: Optional[str] = None,
             compact: bool = False):
    """
    Readings of one pollutant for all stations in a time range (UTC, end inclusive).
    - start only, with a time  -> that single hour
    - start only, a date       -> the whole day
    - a date as `end`          -> up to the end of that day
    - compact=true             -> per station: i = hours since `t0`, v = values (much smaller for long ranges)
    """
    t0 = parse_time(start).floor("h")
    t1 = parse_time(end if end else start, end_of_day=True)
    if t1 < t0:
        raise HTTPException(400, "`end` is before `start`.")

    df = BY_POLLUTANT[pollutant].loc[t0:t1]
    if source:
        df = df[df["source"] == source]
    if station_id:
        df = df[df["station_id"] == station_id]
    limit = MAX_ROWS_COMPACT if compact else MAX_ROWS
    if len(df) > limit:
        raise HTTPException(400, f"{len(df)} rows requested (limit {limit}). "
                                 f"Narrow the time range or filter" + ("" if compact else ", or use compact=true."))

    result = []
    for (src, sid), g in df.groupby(["source", "station_id"], sort=True):
        st = {k: v for k, v in STATIONS[(src, sid)].items() if k not in ("coverage", "pollutants")}
        if compact:
            st["i"] = ((g.index - t0) // pd.Timedelta(hours=1)).tolist()
            st["v"] = g["value"].round(2).tolist()
        else:
            st["readings"] = [{"time_utc": t, "value": round(float(v), 2)}
                              for t, v in zip(g.index.strftime(TIME_FMT), g["value"])]
        result.append(st)

    out = {"pollutant": pollutant, "unit": "µg/m³",
           "start": t0.strftime(TIME_FMT), "end": t1.strftime(TIME_FMT),
           "n_stations": len(result), "n_readings": int(len(df)), "stations": result}
    if compact:
        out["t0"] = t0.strftime(TIME_FMT)
        out["format"] = "reading k of a station: value v[k] at time t0 + i[k] hours"
    return out
	
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False)