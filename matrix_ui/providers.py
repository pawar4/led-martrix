"""Source types for specific services. Importing this module registers them."""
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

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


def resolve_day(day, today=None):
    """'today' / 'tomorrow' / 'YYYY-MM-DD' -> a date."""
    today = today or date.today()
    if day == "today":
        return today
    if day == "tomorrow":
        return today + timedelta(days=1)
    return date.fromisoformat(day)


def hour_label(h):
    """0 -> '12am', 6 -> '6am', 12 -> '12pm', 15 -> '3pm'."""
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


def fetch_forecast(lat, lon, day="today", step_hours=3, units="fahrenheit", start_hour=6, end_hour=22, timeout=10):
    """{"date_label", "slots": [{"hour", "code", "temp_label"}, ...]}: a slot every `step_hours` from
    `start_hour` up to and including `end_hour` of `day`."""
    d = resolve_day(day)
    qs = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,weather_code",
        "temperature_unit": units,
        "timezone": "auto",
        "start_date": d.isoformat(), "end_date": d.isoformat(),
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=timeout) as r:
        hourly = json.load(r)["hourly"]
    slots = [{"hour": hour_label(h), "code": hourly["weather_code"][h],
              "temp_label": f"{round(hourly['temperature_2m'][h])}{units[0].upper()}"}
             for h in range(start_hour, end_hour + 1, step_hours)]
    return {"date_label": d.strftime("%a %b %d"), "slots": slots}


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


def v_day(v):
    if v not in ("today", "tomorrow"):
        try:
            date.fromisoformat(v)
        except (TypeError, ValueError):
            raise ValueError(f"expected 'today', 'tomorrow' or a YYYY-MM-DD date, got {v!r}")
    return v


def v_step_hours(v):
    if isinstance(v, bool) or v not in (1, 2, 3, 4, 6, 8, 12):
        raise ValueError(f"expected a divisor of 24 (1, 2, 3, 4, 6, 8 or 12), got {v!r}")
    return v


def v_hour(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 23:
        raise ValueError(f"expected an hour from 0 to 23, got {v!r}")
    return v


def v_nonneg(v):
    if v_number(v) < 0:
        raise ValueError(f"expected a non-negative number, got {v!r}")
    return v


@source_type("weather", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED),
             units=(v_units, "fahrenheit"), interval=(v_interval, 600))
def _weather(mount, lat, lon, units, interval):
    return PollingSource(lambda: fetch_weather(lat, lon, units), interval, mount)


@source_type("weather_forecast", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED), day=(v_day, "today"),
             step_hours=(v_step_hours, 3), start_hour=(v_hour, 6), end_hour=(v_hour, 22),
             units=(v_units, "fahrenheit"), interval=(v_interval, 1800))
def _weather_forecast(mount, lat, lon, day, step_hours, start_hour, end_hour, units, interval):
    if end_hour < start_hour:
        raise ConfigError(f"weather_forecast: end_hour {end_hour} is before start_hour {start_hour}")
    return PollingSource(lambda: fetch_forecast(lat, lon, day, step_hours, units, start_hour, end_hour), interval, mount)


@source_type("mta_arrivals", stations=(v_stations, REQUIRED), walk_minutes=(v_nonneg, 0),
             max_arrivals=(v_nonneg, 3), interval=(v_interval, 30))
def _mta_arrivals(mount, stations, walk_minutes, max_arrivals, interval):
    return PollingSource(lambda: fetch_arrivals(stations, walk_minutes, int(max_arrivals)), interval, mount)
