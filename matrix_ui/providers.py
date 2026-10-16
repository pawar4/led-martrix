"""Source types for specific services. Importing this module registers them."""
import json
import logging
import random
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .resolver import ConfigError
from .sources import REQUIRED, PollingSource, Source, source_type, v_interval, v_number, v_str

log = logging.getLogger(__name__)


def fetch_weather(lat, lon, units="fahrenheit", timeout=10):
    qs = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,weather_code,is_day",
        "temperature_unit": units,
        "timezone": "auto",
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=timeout) as r:
        cur = json.load(r)["current"]
    return {"code": cur["weather_code"], "is_day": bool(cur["is_day"]),
            "temp_label": f"{int(cur['temperature_2m'])}{units[0].upper()}"}


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


def fetch_forecast(lat, lon, day="today", step_hours=3, units="fahrenheit", start_hour=6, end_hour=22, count=6, timeout=10):
    """{"date_label", "slots": [{"hour", "code", "temp_label"}, ...]}: a slot every `step_hours` from
    `start_hour` up to and including `end_hour` of `day`. With day="now", `count` slots every `step_hours`
    starting at the current hour at the location (start_hour/end_hour are ignored)."""
    rolling = day == "now"
    d = date.today() if rolling else resolve_day(day)
    last = d + timedelta(days=1) if rolling else d
    qs = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,weather_code,is_day",
        "temperature_unit": units,
        "timezone": "auto",
        "start_date": (d - timedelta(days=1)).isoformat() if rolling else d.isoformat(),
        "end_date": (last + timedelta(days=1)).isoformat() if rolling else d.isoformat(),
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=timeout) as r:
        data = json.load(r)
    hourly = data["hourly"]
    if rolling:
        # hourly["time"] is local to the location; find the current local hour in it
        local = datetime.now(timezone.utc) + timedelta(seconds=data.get("utc_offset_seconds", 0))
        d = local.date()
        first = hourly["time"].index(local.strftime("%Y-%m-%dT%H:00"))
        indexes = [first + i * step_hours for i in range(count)]
        hours = [(local.hour + i * step_hours) % 24 for i in range(count)]
    else:
        indexes = hours = list(range(start_hour, end_hour + 1, step_hours))
    slots = [{"hour": hour_label(h), "code": hourly["weather_code"][i], "is_day": bool(hourly["is_day"][i]),
              "temp_label": f"{round(hourly['temperature_2m'][i])}{units[0].upper()}"}
             for i, h in zip(indexes, hours)]
    return {"date_label": d.strftime("%a %b %d"), "slots": slots}


RANGES = {"intraday": ("1d", "5m"), "3day": ("5d", "15m")}


def fetch_quote(symbol, label=None, range_="intraday", timeout=10):
    """Price and chart from Yahoo Finance (no key). `change` is measured against `baseline`: the previous
    close for "intraday", the first point of the last three trading days for "3day"."""
    span, step = RANGES[range_]
    qs = urllib.parse.urlencode({"range": span, "interval": step})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        result = json.load(r)["chart"]["result"][0]
    return quote_from_chart(symbol, label, range_, result["meta"], result.get("timestamp") or [],
                            result["indicators"]["quote"][0]["close"])


def quote_from_chart(symbol, label, range_, meta, timestamps, closes):
    offset = meta.get("gmtoffset", 0)
    points = [(datetime.fromtimestamp(t + offset, timezone.utc).date(), c)
              for t, c in zip(timestamps, closes) if c is not None]
    if range_ == "3day":
        days = sorted({d for d, _ in points})[-3:]
        points = [(d, c) for d, c in points if d in days]
    if not points:
        raise ValueError(f"no price data for {symbol}")
    values = [c for _, c in points]
    dividers = [i for i in range(1, len(points)) if points[i][0] != points[i - 1][0]]
    price = meta.get("regularMarketPrice", values[-1])
    baseline = meta.get("chartPreviousClose", values[0]) if range_ == "intraday" else values[0]
    change = price - baseline
    pct = change / baseline * 100 if baseline else 0
    return {
        "label": label or symbol,
        "range_label": "1D" if range_ == "intraday" else "3D",
        "price_label": f"{price:,.2f}",
        "change_label": f"{'+' if change >= 0 else '-'}{abs(pct):.2f}%",
        "color": "green" if change >= 0 else "red",
        "baseline": baseline,
        "values": values,
        "dividers": dividers,
    }


def fetch_arrivals(stations, walk_minutes, max_arrivals):
    """{route: {"name", "direction", "arrivals": [minutes, ...]}}. If any feed raises, the whole poll fails."""
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
        out[route] = {"name": cfg["name"], "direction": cfg["direction"], "arrivals": arrivals[:max_arrivals]}
    return out


ALERTS_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts.json"
# (alert_type substring, rank, label, colour): the worst alert on a route sets its status
ALERT_RANKS = [("Suspended", 4, "Suspended", "red"), ("No Scheduled", 4, "No service", "red"),
               ("Delays", 3, "Delays", "orange")]
IGNORED_ALERTS = ("Station Notice", "Extra Service")
GOOD_SERVICE = {"label": "All clear", "color": "green", "headline": "", "rank": 0}


def alert_rank(alert_type):
    """(rank, label, colour) for an alert type, or None for alerts that don't affect service."""
    if any(i in alert_type for i in IGNORED_ALERTS):
        return None
    for needle, rank, label, color in ALERT_RANKS:
        if needle in alert_type:
            return rank, label, color
    return 1, "Svc change", "yellow"


def first_sentence(text):
    return text.strip().split("\n")[0].split(". ")[0].strip().rstrip(".") + "."


def alerts_from_feed(feed, routes, now=None):
    """{route: {"label", "color", "headline", "rank"}} from a GTFS-realtime alerts feed (as JSON): the worst active
    alert on each of `routes`, or "All clear". `headline` is that alert's first sentence."""
    now = now if now is not None else time.time()
    out = {r: dict(GOOD_SERVICE) for r in routes}
    best = {}
    for entity in feed.get("entity", []):
        alert = entity.get("alert", {})
        periods = alert.get("active_period") or [{}]
        if not any(p.get("start", 0) <= now <= p.get("end", float("inf")) for p in periods):
            continue
        ranked = alert_rank(alert.get("transit_realtime.mercury_alert", {}).get("alert_type", ""))
        texts = [t["text"] for t in alert.get("header_text", {}).get("translation", []) if t.get("language") == "en"]
        if not ranked or not texts:
            continue
        for route in {i.get("route_id") for i in alert.get("informed_entity", [])} & set(routes):
            if route not in best or ranked[0] > best[route][0]:
                best[route] = ranked
                out[route] = {"label": ranked[1], "color": ranked[2], "headline": first_sentence(texts[0]), "rank": ranked[0]}
    return out


def fetch_alerts(routes, timeout=10):
    """Active subway service alerts for `routes`, plus `headline` (the worst one overall) and `count`."""
    req = urllib.request.Request(ALERTS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        feed = json.load(r)
    out = alerts_from_feed(feed, routes)
    worst = max(out.values(), key=lambda a: a["rank"])
    return {**out, "headline": worst["headline"] or "No service alerts for " + ", ".join(routes) + ".",
            "count": sum(a["rank"] > 0 for a in out.values())}


def clock_label(t):
    """datetime -> '7:06am'."""
    return f"{t.hour % 12 or 12}:{t.minute:02}{'am' if t.hour < 12 else 'pm'}"


def daylight_now(sun_times, now):
    """Daylight state from `sun_times` ([(sunrise, sunset), ...] for consecutive local days,
    naive datetimes) and the local time `now`. `progress` is how far through the current day or night we are."""
    events = sorted(t for pair in sun_times for t in pair)
    prev = max((t for t in events if t <= now), default=None)
    nxt = min((t for t in events if t > now), default=None)
    is_day = any(rise <= now < sett for rise, sett in sun_times)
    out = {"phase": "day" if is_day else "night", "color": "yellow" if is_day else "blue",
           "progress": 0, "next_label": ""}
    if prev and nxt:
        out["progress"] = (now - prev) / (nxt - prev)
    if nxt:
        mins = int((nxt - now).total_seconds() // 60)
        out["next_label"] = f"{'Sunset' if is_day else 'Rise'} {mins // 60}h{mins % 60:02}m"
    today = next((p for p in sun_times if p[0].date() == now.date()), None)
    if today:
        out["sunrise_label"], out["sunset_label"] = clock_label(today[0]), clock_label(today[1])
    return out


def fetch_sun_times(lat, lon, timeout=10):
    """([(sunrise, sunset), ...] for yesterday, today and tomorrow as naive local datetimes, utc offset in s)."""
    qs = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "daily": "sunrise,sunset",
                                 "timezone": "auto", "past_days": 1, "forecast_days": 2})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=timeout) as r:
        data = json.load(r)
    daily = data["daily"]
    pairs = [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in zip(daily["sunrise"], daily["sunset"])]
    return pairs, data.get("utc_offset_seconds", 0)


def daylight_fetcher(lat, lon, fetch=fetch_sun_times):
    """A fetch callable for PollingSource: sun times are fetched once per local day, the rest is computed."""
    cache = {}

    def fetch_daylight():
        utc = datetime.now(timezone.utc)
        if not cache or cache["valid_until"] <= utc.timestamp():
            pairs, offset = fetch(lat, lon)
            # the offset can change with daylight saving, so refetch at least every 6 hours
            cache.update(pairs=pairs, offset=offset, valid_until=utc.timestamp() + 6 * 3600)
        local = (utc + timedelta(seconds=cache["offset"])).replace(tzinfo=None)
        return daylight_now(cache["pairs"], local)
    return fetch_daylight


def load_clues(path):
    """Read a clue bank: a JSON list of {category, value, clue, answer}."""
    try:
        with open(path) as f:
            clues = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read clues from {path}: {e}")
    if not isinstance(clues, list) or not clues:
        raise ValueError(f"{path}: expected a non-empty list of clues")
    for i, c in enumerate(clues):
        if (not isinstance(c, dict) or set(c) != {"category", "value", "clue", "answer"}
                or not all(isinstance(c[k], str) and c[k] for k in ("category", "clue", "answer"))
                or isinstance(c["value"], bool) or not isinstance(c["value"], int)):
            raise ValueError(f"{path}: clue {i} needs exactly category, value (int), clue, answer")
    return clues


OPENTDB_VALUES = {"easy": 200, "medium": 600, "hard": 1000}


def opentdb_to_clues(results, rng=None):
    """Convert Open Trivia DB multiple-choice results (URL-encoded) into clues. The options are listed in
    the clue as A) to D) and the answer is the matching letter and text. Value follows the difficulty."""
    rng = rng or random.Random()
    unq = urllib.parse.unquote
    clues = []
    for r in results:
        options = [unq(o) for o in r["incorrect_answers"]] + [unq(r["correct_answer"])]
        rng.shuffle(options)
        letters = "ABCDEFGH"[:len(options)]
        correct = letters[options.index(unq(r["correct_answer"]))]
        category = unq(r["category"]).split(":")[-1].strip()
        clues.append({
            "category": category,
            "value": OPENTDB_VALUES.get(r["difficulty"], 600),
            "clue": f"{unq(r['question'])} " + " ".join(f"{l}) {o}" for l, o in zip(letters, options)),
            "answer": f"{correct}) {unq(r['correct_answer'])}",
        })
    return clues


def fetch_opentdb(amount=20, difficulty=None, timeout=10, rng=None):
    """A batch of clues from Open Trivia DB (free, no key; it allows one request per 5 seconds)."""
    params = {"amount": amount, "type": "multiple", "encode": "url3986"}
    if difficulty:
        params["difficulty"] = difficulty
    with urllib.request.urlopen(f"https://opentdb.com/api.php?{urllib.parse.urlencode(params)}", timeout=timeout) as r:
        body = json.load(r)
    if body.get("response_code") != 0:
        raise ValueError(f"Open Trivia DB returned response_code {body.get('response_code')}")
    return opentdb_to_clues(body["results"], rng)


def scroll_position(elapsed, duration, hold=1.5):
    """0 to 1 over `duration` seconds: rests at 0 for `hold` seconds, moves, then rests at 1 for `hold`."""
    hold = min(hold, duration / 4)
    return min(max((elapsed - hold) / (duration - 2 * hold), 0), 1)


def trivia_frame(clue, elapsed, question_seconds, reveal_seconds, count_label=""):
    """What the screen shows `elapsed` seconds into a clue: the clue with a draining timer bar, then the
    answer with a second, shorter bar. `scroll` (0 to 1) moves through text too long for the box, once per phase.
    `count_label` is the position in the round ("2/5"). Text is upper-cased in the Jeopardy style (answers keep
    their case)."""
    head = {"category": clue["category"].upper(), "value_label": f"${clue['value']}", "count_label": count_label}
    if elapsed < question_seconds:
        return {**head, "phase": "question", "body": clue["clue"].upper(), "body_color": "white",
                "bar_color": "yellow", "progress": 1 - elapsed / question_seconds,
                "scroll": scroll_position(elapsed, question_seconds)}
    t = elapsed - question_seconds
    return {**head, "phase": "reveal", "body": clue["answer"], "body_color": "green",
            "bar_color": "green", "progress": max(1 - t / reveal_seconds, 0),
            "scroll": scroll_position(t, reveal_seconds)}


class TriviaSource(Source):
    """Plays rounds of `questions` clues, each shown for `question_seconds` and then its answer for
    `reveal_seconds`, for one round only; it then holds the last answer. Republishes `tick` seconds apart so the timer bar moves; the
    screen needs no clock of its own.

    Rounds come from the clue bank in shuffled order, with no repeats until every clue has been shown. With
    `fetch_batch` (a callable taking a count and returning a list of clues), each round is fetched from it
    instead, falling back to the bank when it fails or returns nothing."""

    def __init__(self, clues, question_seconds, reveal_seconds, mount, questions=5, tick=0.1, rng=None,
                 clock=time.monotonic, fetch_batch=None):
        super().__init__(mount)
        self.fetch_batch = fetch_batch
        self.clues = clues
        self.questions = questions
        self.question_seconds = question_seconds
        self.reveal_seconds = reveal_seconds
        self.tick = tick
        self.rng = rng or random.Random()
        self.clock = clock
        self._queue = []        # shuffled bank clues not yet played

    def order(self, previous=None):
        """A fresh shuffle that doesn't open with the clue that just closed the last one."""
        clues = list(self.clues)
        self.rng.shuffle(clues)
        if len(clues) > 1 and clues[0] is previous:
            clues.append(clues.pop(0))
        return clues

    def next_round(self, previous=None):
        """The clues for one round: `questions` of them (fewer if the bank is smaller)."""
        if self.fetch_batch:
            try:
                batch = self.fetch_batch(self.questions)
                if batch:
                    return list(batch)[:self.questions]
            except Exception as e:      # offline, rate limited, bad response: play the local bank
                log.warning("%s fetch failed, using the local clues: %s", self.mount, e)
        n = min(self.questions, len(self.clues))
        if len(self._queue) < n:        # top up with a new shuffle, leaving out clues still waiting
            self._queue += [c for c in self.order(previous) if all(c is not q for q in self._queue)]
        clues, self._queue = self._queue[:n], self._queue[n:]
        return clues

    def _run(self):
        total = self.question_seconds + self.reveal_seconds
        clues = self.next_round()
        for i, clue in enumerate(clues, 1):
            start = self.clock()
            while not self._stop.is_set() and self.clock() - start < total:
                self.publish(trivia_frame(clue, self.clock() - start, self.question_seconds,
                                          self.reveal_seconds, f"{i}/{len(clues)}"))
                self._stop.wait(self.tick)
        if clues and not self._stop.is_set():       # one round only: hold the last answer, no refetch
            self.publish(trivia_frame(clues[-1], total, self.question_seconds, self.reveal_seconds,
                                      f"{len(clues)}/{len(clues)}"))


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


def v_routes(v):
    if not isinstance(v, list) or not v or not all(isinstance(r, str) and r for r in v):
        raise ValueError(f"expected a non-empty list of route names like ['E', '7'], got {v!r}")
    return v


def v_day(v):
    if v not in ("now", "today", "tomorrow"):
        try:
            date.fromisoformat(v)
        except (TypeError, ValueError):
            raise ValueError(f"expected 'now', 'today', 'tomorrow' or a YYYY-MM-DD date, got {v!r}")
    return v


def v_step_hours(v):
    if isinstance(v, bool) or v not in (1, 2, 3, 4, 6, 8, 12):
        raise ValueError(f"expected a divisor of 24 (1, 2, 3, 4, 6, 8 or 12), got {v!r}")
    return v


def v_count(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 8:
        raise ValueError(f"expected a slot count from 1 to 8, got {v!r}")
    return v


def v_hour(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 23:
        raise ValueError(f"expected an hour from 0 to 23, got {v!r}")
    return v


def v_oneof(*options):
    def check(v):
        if v not in options:
            raise ValueError(f"expected one of {list(options)}, got {v!r}")
        return v
    return check


def v_nonneg(v):
    if v_number(v) < 0:
        raise ValueError(f"expected a non-negative number, got {v!r}")
    return v


@source_type("weather", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED),
             units=(v_units, "fahrenheit"), interval=(v_interval, 600))
def _weather(mount, lat, lon, units, interval):
    return PollingSource(lambda: fetch_weather(lat, lon, units), interval, mount)


@source_type("weather_forecast", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED), day=(v_day, "today"),
             step_hours=(v_step_hours, 3), start_hour=(v_hour, 6), end_hour=(v_hour, 22), count=(v_count, 6),
             units=(v_units, "fahrenheit"), interval=(v_interval, 1800))
def _weather_forecast(mount, lat, lon, day, step_hours, start_hour, end_hour, count, units, interval):
    if end_hour < start_hour:
        raise ConfigError(f"weather_forecast: end_hour {end_hour} is before start_hour {start_hour}")
    return PollingSource(lambda: fetch_forecast(lat, lon, day, step_hours, units, start_hour, end_hour, count), interval, mount)


@source_type("market_quote", symbol=(v_str, REQUIRED), label=(v_str, None),
             range=(v_oneof("intraday", "3day"), "intraday"), interval=(v_interval, 60))
def _market_quote(mount, symbol, label, range, interval):
    return PollingSource(lambda: fetch_quote(symbol, label, range), interval, mount)


@source_type("mta_arrivals", stations=(v_stations, REQUIRED), walk_minutes=(v_nonneg, 0),
             max_arrivals=(v_nonneg, 3), interval=(v_interval, 30))
def _mta_arrivals(mount, stations, walk_minutes, max_arrivals, interval):
    return PollingSource(lambda: fetch_arrivals(stations, walk_minutes, int(max_arrivals)), interval, mount)


@source_type("mta_alerts", routes=(v_routes, REQUIRED), interval=(v_interval, 120))
def _mta_alerts(mount, routes, interval):
    return PollingSource(lambda: fetch_alerts(routes), interval, mount)


@source_type("daylight", lat=(v_number, REQUIRED), lon=(v_number, REQUIRED), interval=(v_interval, 60))
def _daylight(mount, lat, lon, interval):
    return PollingSource(daylight_fetcher(lat, lon), interval, mount)


def v_questions(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 50:
        raise ValueError(f"expected a whole number from 1 to 50, got {v!r}")
    return v


@source_type("trivia", path=(v_str, REQUIRED), question_seconds=(v_interval, 15), reveal_seconds=(v_interval, 5),
             provider=(v_oneof("local", "opentdb"), "local"), difficulty=(v_oneof("easy", "medium", "hard"), None),
             questions=(v_questions, 5))
def _trivia(mount, path, question_seconds, reveal_seconds, provider, difficulty, questions):
    fetch = (lambda n: fetch_opentdb(n, difficulty)) if provider == "opentdb" else None
    return TriviaSource(load_clues(path), question_seconds, reveal_seconds, mount, questions, fetch_batch=fetch)
