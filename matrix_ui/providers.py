"""Source types for specific services. Importing this module registers them."""
import json
import urllib.parse
import urllib.request
from datetime import datetime

from .resolver import ConfigError
from .sources import REQUIRED, PollingSource, source_type, v_interval, v_number, v_str


def fetch_weather(lat, lon, units="fahrenheit", timeout=10):
    qs = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code",
        "temperature_unit": units,
        "timezone": "auto",
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=timeout) as r:
        cur = json.load(r)["current"]
    return {"code": cur["weather_code"], "temp_label": f"{int(cur['temperature_2m'])}{units[0].upper()}"}


def fetch_arrivals(stations, walk_minutes, max_arrivals):
    """{route: {"name", "arrivals": [minutes, ...]}}. If any feed raises, the whole poll fails."""
    from nyct_gtfs import NYCTFeed      # imported lazily: only needed for live data

    out = {}
    now = datetime.now()
    for route, cfg in stations.items():
        stop = f"{cfg['stop_id']}{cfg['direction']}"
        arrivals = sorted(
            int(mins)
            for train in NYCTFeed(route).filter_trips(underway=True)
            for st in train.stop_time_updates
            if st.stop_id == stop and (mins := (st.arrival - now).total_seconds() / 60) >= walk_minutes
        )
        out[route] = {"name": cfg["name"], "arrivals": arrivals[:max_arrivals]}
    return out


def v_units(v):
    if v not in ("fahrenheit", "celsius"):
        raise ValueError(f"expected 'fahrenheit' or 'celsius', got {v!r}")
    return v


def v_stations(v):
    if not isinstance(v, dict) or not v:
        raise ValueError("expected an object of {route: {stop_id, direction, name}}")
    for route, cfg in v.items():
        if not isinstance(cfg, dict) or set(cfg) != {"stop_id", "direction", "name"}:
            raise ValueError(f"station '{route}' needs exactly stop_id, direction, name")
        v_str(cfg["stop_id"]), v_str(cfg["name"])
        if cfg["direction"] not in ("N", "S"):
            raise ValueError(f"station '{route}': direction must be 'N' or 'S'")
    return v


def v_nonneg(v):
    if v_number(v) < 0:
        raise ValueError(f"expected a non-negative number, got {v!r}")
    return v


@source_type("weather", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED),
             units=(v_units, "fahrenheit"), interval=(v_interval, 600))
def _weather(mount, lat, lon, units, interval):
    return PollingSource(lambda: fetch_weather(lat, lon, units), interval, mount)


@source_type("mta_arrivals", stations=(v_stations, REQUIRED), walk_minutes=(v_nonneg, 0),
             max_arrivals=(v_nonneg, 3), interval=(v_interval, 30))
def _mta_arrivals(mount, stations, walk_minutes, max_arrivals, interval):
    return PollingSource(lambda: fetch_arrivals(stations, walk_minutes, int(max_arrivals)), interval, mount)
