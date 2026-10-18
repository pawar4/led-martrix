import json
import threading
import time

from matrix_ui import DataModel, PollingSource, StaticFileSource


def wait_for(cond, timeout=2):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_polling_publishes_at_mount():
    dm = DataModel()
    src = PollingSource(lambda: {"temp": 72}, interval=0.01, mount="/weather").start(dm)
    try:
        assert wait_for(lambda: dm.get("/weather/temp") == 72)
        assert src.age() is not None
    finally:
        src.stop()


def test_polling_keeps_last_good_data_on_failure():
    dm = DataModel()
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("down")
        return {"v": 1}

    src = PollingSource(fetch, interval=0.01, mount="/x").start(dm)
    try:
        assert wait_for(lambda: len(calls) > 3)
        assert dm.get("/x/v") == 1
    finally:
        src.stop()


def test_static_file_reloads_on_change(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"a": 1}))
    dm = DataModel()
    src = StaticFileSource(str(p), interval=0.01).start(dm)
    try:
        assert wait_for(lambda: dm.get("/a") == 1)
        time.sleep(0.02)
        p.write_text(json.dumps({"a": 2}))
        assert wait_for(lambda: dm.get("/a") == 2)
    finally:
        src.stop()


# ---- config-driven sources ----

import os

import pytest

from matrix_ui import ConfigError, Surface
from matrix_ui.sources import build_source, build_sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_subway_screen_declares_its_sources():
    surface = Surface.load(os.path.join(ROOT, "screens", "subway.json"))
    assert sorted(s.mount for s in surface.sources) == ["/alerts", "/trains", "/weather"]


def test_screen_without_sources_loads():
    surface = Surface.load({"root": "r", "components": [{"id": "r", "component": "Text", "text": "hi"}]})
    assert surface.sources == []


@pytest.mark.parametrize("spec, message", [
    ({"type": "nope", "mount": "/x"}, "unknown type"),
    ({"type": "weather", "mount": "/w", "lat": 1}, "'lon' is required"),
    ({"type": "weather", "lat": 1, "lon": 2}, "'mount' is required"),
    ({"type": "weather", "mount": "w", "lat": 1, "lon": 2}, "starting with '/'"),
    ({"type": "weather", "mount": "/w", "lat": 1, "lon": 2, "bogus": 1}, "unknown keys"),
    ({"type": "http_json", "mount": "/x", "url": "http://h", "interval": 0}, "positive"),
    ({"type": "weather_forecast", "mount": "/f", "lat": 1, "lon": 2, "day": "friday"}, "YYYY-MM-DD"),
    ({"type": "weather_forecast", "mount": "/f", "lat": 1, "lon": 2, "step_hours": 5}, "divisor of 24"),
    ({"type": "weather_forecast", "mount": "/f", "lat": 1, "lon": 2, "start_hour": 24}, "0 to 23"),
    ({"type": "weather_forecast", "mount": "/f", "lat": 1, "lon": 2, "start_hour": 20, "end_hour": 6}, "before start_hour"),
    ({"type": "mta_arrivals", "mount": "/t", "stations": {"E": {"stop_id": "F09"}}}, "exactly"),
    ({"type": "nfl_scores", "mount": "/n", "day": "now"}, "got 'now'"),
    ({"type": "nfl_scores", "mount": "/n", "day": "friday"}, "YYYY-MM-DD"),
    ({"type": "nfl_scores", "mount": "/n", "slots": 0}, "game cards"),
    ({"type": "nfl_scores", "mount": "/n", "slots": 33}, "game cards"),
    ({"type": "nfl_scores", "mount": "/n", "columns": 5}, "cards per row"),
    ({"type": "nfl_scores", "mount": "/n", "row_height": 0}, "row height"),
    ({"type": "nfl_scores", "mount": "/n", "per_page": 4}, "unknown keys"),
    ({"type": "nfl_scores", "mount": "/n", "interval": 0}, "positive"),
])
def test_bad_source_specs_are_rejected(spec, message):
    with pytest.raises(ConfigError, match=message):
        build_source(spec)


def test_overlapping_mounts_are_rejected():
    a = {"type": "file", "path": "a.json", "mount": "/trains"}
    b = {"type": "file", "path": "b.json", "mount": "/trains/E"}
    with pytest.raises(ConfigError, match="overlap"):
        build_sources([a, b])


def test_http_json_expands_env_in_headers(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    build_source({"type": "http_json", "mount": "/x", "url": "http://h/${TEST_KEY}", "headers": {"k": "${TEST_KEY}"}})
    monkeypatch.delenv("TEST_KEY")
    with pytest.raises(ConfigError, match="TEST_KEY is not set"):
        build_source({"type": "http_json", "mount": "/x", "url": "http://h/${TEST_KEY}"})


def test_surface_starts_and_stops_sources(tmp_path):
    p = tmp_path / "d.json"
    p.write_text('{"a": 5}')
    surface = Surface.load({"root": "r", "components": [{"id": "r", "component": "Text", "text": "hi"}],
                            "sources": [{"type": "file", "path": str(p), "mount": "/d", "interval": 0.01}]})
    dm = DataModel()
    surface.start_sources(dm)
    try:
        assert wait_for(lambda: dm.get("/d/a") == 5)
    finally:
        surface.stop_sources()


def test_resolve_day_and_hour_label():
    from datetime import date
    from matrix_ui.providers import hour_label, resolve_day
    today = date(2026, 10, 11)
    assert resolve_day("today", today) == today
    assert resolve_day("tomorrow", today) == date(2026, 10, 12)
    assert resolve_day("2026-10-20", today) == date(2026, 10, 20)
    assert [hour_label(h) for h in (0, 3, 12, 15, 21)] == ["12am", "3am", "12pm", "3pm", "9pm"]


def test_temp_color_bands():
    from matrix_ui.providers import temp_color
    assert [temp_color(t) for t in (-5, 40, 41, 62, 84, 85, 100)] == [
        "blue", "blue", "yellow", "yellow", "yellow", "red", "red"]
    assert [temp_color(t, "celsius") for t in (-5, 4, 5, 20, 28, 29, 40)] == [
        "blue", "blue", "yellow", "yellow", "yellow", "red", "red"]


def test_fetch_weather_reports_day_or_night(monkeypatch):
    import io
    import json as _json
    from matrix_ui import providers
    for is_day in (1, 0):
        body = {"current": {"temperature_2m": 61.7, "weather_code": 0, "is_day": is_day}}
        monkeypatch.setattr(providers.urllib.request, "urlopen",
                            lambda url, timeout, body=body: io.StringIO(_json.dumps(body)))
        assert providers.fetch_weather(1, 2) == {"code": 0, "is_day": bool(is_day), "temp_label": "61F"}


def test_fetch_forecast_samples_every_step(monkeypatch):
    import io
    import json as _json
    from matrix_ui import providers
    hourly = {"temperature_2m": [h + 0.4 for h in range(24)], "weather_code": list(range(24)),
              "is_day": [int(7 <= h < 19) for h in range(24)]}
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda url, timeout: io.StringIO(_json.dumps({"hourly": hourly})))
    out = providers.fetch_forecast(1, 2, "2026-10-17", step_hours=6, start_hour=0, end_hour=23)
    assert out["date_label"] == "Sat Oct 17"
    assert out["slots"] == [{"hour": "12am", "code": 0, "is_day": False, "temp_label": "0F", "temp_color": "blue"},
                            {"hour": "6am", "code": 6, "is_day": False, "temp_label": "6F", "temp_color": "blue"},
                            {"hour": "12pm", "code": 12, "is_day": True, "temp_label": "12F", "temp_color": "blue"},
                            {"hour": "6pm", "code": 18, "is_day": True, "temp_label": "18F", "temp_color": "blue"}]
    default = providers.fetch_forecast(1, 2, "2026-10-17")      # 6am to 10pm every 3 hours
    assert [s["hour"] for s in default["slots"]] == ["6am", "9am", "12pm", "3pm", "6pm", "9pm"]


def _chart(day_count, per_day=3):
    base = 1_760_000_000      # a Tuesday, 2025
    ts, closes = [], []
    for d in range(day_count):
        for i in range(per_day):
            ts.append(base + d * 86400 + i * 900)
            closes.append(100 + d * 10 + i)
    return ts, closes


def test_quote_intraday_uses_previous_close_for_change():
    from matrix_ui.providers import quote_from_chart
    ts, closes = _chart(1)
    meta = {"regularMarketPrice": 110.0, "chartPreviousClose": 100.0, "gmtoffset": 0}
    q = quote_from_chart("X", "Ex", "intraday", meta, ts, closes)
    assert (q["label"], q["range_label"], q["price_label"], q["change_label"], q["color"]) == ("Ex", "1D", "110.00", "+10.00%", "green")
    assert q["baseline"] == 100.0 and q["values"] == closes


def test_quote_3day_keeps_last_three_days_and_skips_gaps():
    from matrix_ui.providers import quote_from_chart
    ts, closes = _chart(5)
    closes[7] = None
    q = quote_from_chart("X", None, "3day", {"regularMarketPrice": 90.0, "gmtoffset": 0}, ts, closes)
    assert len(q["values"]) == 8 and q["values"][0] == 120      # days 2-4, one gap dropped
    assert q["label"] == "X" and q["range_label"] == "3D"
    assert q["baseline"] == 120 and q["change_label"] == "-25.00%" and q["color"] == "red"
    assert len(q["dividers"]) == 2 and all(q["dividers"][i] > 0 for i in range(2))   # one split per day boundary


def test_quote_1month_measures_from_first_point_and_splits_on_weeks():
    from matrix_ui.providers import quote_from_chart
    monday = 1_759_761_000      # Mon 2025-10-06 14:30 UTC
    days = [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15]     # weekdays over three weeks
    ts = [monday + d * 86400 for d in days]
    closes = [100 + i for i in range(len(days))]
    q = quote_from_chart("X", None, "1month", {"regularMarketPrice": 112.0, "gmtoffset": 0}, ts, closes)
    assert q["range_label"] == "1M" and q["values"] == closes
    assert q["baseline"] == 100 and q["change_label"] == "+12.00%" and q["color"] == "green"
    assert q["dividers"] == [5, 10]         # the first point of the 2nd and 3rd weeks, not of every day


def test_market_quote_source_validation():
    assert build_source({"type": "market_quote", "mount": "/m", "symbol": "^GSPC", "range": "3day"}).mount == "/m"
    assert build_source({"type": "market_quote", "mount": "/m", "symbol": "^GSPC", "range": "1month"}).mount == "/m"
    with pytest.raises(ConfigError, match="intraday"):
        build_source({"type": "market_quote", "mount": "/m", "symbol": "X", "range": "week"})
    with pytest.raises(ConfigError, match="'symbol' is required"):
        build_source({"type": "market_quote", "mount": "/m"})


# ---- trivia ----

CLUES = [{"category": "Science", "value": 200, "clue": "Planet we live on", "answer": "What is Earth?"},
         {"category": "Geography", "value": 400, "clue": "Capital of France", "answer": "What is Paris?"}]


def test_trivia_frame_runs_question_then_reveal():
    from matrix_ui.providers import trivia_frame
    q = trivia_frame(CLUES[0], 5, 20, 10, "2/5")
    assert (q["phase"], q["category"], q["value_label"], q["body"], q["body_color"]) == \
        ("question", "SCIENCE", "$200", "PLANET WE LIVE ON", "white")
    assert q["progress"] == 0.75 and q["bar_color"] == "yellow" and q["scroll"] == pytest.approx(3.5 / 17) and q["count_label"] == "2/5"
    r = trivia_frame(CLUES[0], 25, 20, 10)
    assert (r["phase"], r["body"], r["body_color"], r["bar_color"]) == ("reveal", "What is Earth?", "green", "green")
    assert r["progress"] == 0.5
    assert trivia_frame(CLUES[0], 31, 20, 10)["progress"] == 0


def test_scroll_position_holds_at_both_ends():
    from matrix_ui.providers import scroll_position
    assert [scroll_position(t, 15) for t in (0, 1.5, 7.5, 13.5, 15)] == [0, 0, 0.5, 1, 1]
    assert scroll_position(1, 4) == 0 and scroll_position(3, 4) == 1      # short phases hold for a quarter each end


def test_trivia_source_plays_each_clue_before_repeating():
    import random
    from matrix_ui.providers import TriviaSource
    src = TriviaSource(CLUES, 1, 1, "/t", rng=random.Random(0))
    first = src.order()
    assert sorted(c["value"] for c in first) == [200, 400]
    assert src.order(previous=first[0])[0] is not first[0]      # a new shuffle never opens with the last clue


def test_trivia_source_publishes_both_phases():
    from matrix_ui.providers import TriviaSource
    t = [0.0]
    src = TriviaSource(CLUES[:1], 1, 1, "/trivia", tick=0.01, clock=lambda: t.__setitem__(0, t[0] + 0.1) or t[0])
    seen, dm = set(), DataModel()
    src.start(dm)
    try:
        assert wait_for(lambda: seen.add(dm.get("/trivia/phase")) or seen >= {"question", "reveal"})
    finally:
        src.stop()


def test_trivia_source_config_and_clue_bank(tmp_path):
    import json as _json
    from matrix_ui.providers import load_clues
    bank = tmp_path / "c.json"
    bank.write_text(_json.dumps(CLUES))
    assert build_source({"type": "trivia", "mount": "/t", "path": str(bank), "question_seconds": 10}).mount == "/t"
    assert load_clues(os.path.join(ROOT, "screens", "trivia.clues.json"))      # the shipped bank is valid
    for bad, message in [("[]", "non-empty list"), ('[{"category": "x"}]', "clue 0 needs"),
                         ('[{"category": "x", "value": "1", "clue": "c", "answer": "a"}]', "clue 0 needs"),
                         ("nope", "cannot read")]:
        bank.write_text(bad)
        with pytest.raises(ConfigError, match=message):
            build_source({"type": "trivia", "mount": "/t", "path": str(bank)})
    with pytest.raises(ConfigError, match="cannot read"):
        build_source({"type": "trivia", "mount": "/t", "path": str(tmp_path / "missing.json")})
    with pytest.raises(ConfigError, match="positive"):
        build_source({"type": "trivia", "mount": "/t", "path": str(bank), "reveal_seconds": 0})


def test_trivia_screen_declares_its_source(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert [s.mount for s in Surface.load(os.path.join(ROOT, "screens", "trivia.json")).sources] == ["/trivia"]


def _opentdb_body(code=0):
    from urllib.parse import quote
    q = lambda s: quote(s, safe="")
    return json.dumps({"response_code": code, "results": [] if code else [
        {"category": q("Science: Computers"), "type": "multiple", "difficulty": "hard",
         "question": q("What does CPU stand for?"), "correct_answer": q("Central Processing Unit"),
         "incorrect_answers": [q("Core Power Unit"), q("Central Program Utility"), q("Computer & Peripheral Unit")]},
        {"category": q("History"), "type": "multiple", "difficulty": "easy",
         "question": q("Who painted the Mona Lisa?"), "correct_answer": q("Leonardo da Vinci"),
         "incorrect_answers": [q("Michelangelo"), q("Raphael"), q("Donatello")]}]})


def test_opentdb_results_become_clues(monkeypatch):
    import io
    import random
    from matrix_ui import providers
    seen = []
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda url, timeout: seen.append(url) or io.StringIO(_opentdb_body()))
    clues = providers.fetch_opentdb(2, "hard", rng=random.Random(1))
    assert "amount=2" in seen[0] and "difficulty=hard" in seen[0] and "encode=url3986" in seen[0]
    cpu, mona = clues
    assert (cpu["category"], cpu["value"], mona["value"]) == ("Computers", 1000, 200)
    assert cpu["clue"].startswith("What does CPU stand for? A) ")
    assert "Computer & Peripheral Unit" in cpu["clue"]                    # percent-encoding decoded
    letter, _, text = cpu["answer"].partition(") ")
    assert text == "Central Processing Unit" and f"{letter}) {text}" in cpu["clue"]


def test_opentdb_error_code_raises(monkeypatch):
    import io
    from matrix_ui import providers
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda url, timeout: io.StringIO(_opentdb_body(5)))
    with pytest.raises(ValueError, match="response_code 5"):
        providers.fetch_opentdb()


def test_trivia_round_uses_fetched_batch_and_falls_back_to_the_bank():
    import random
    from matrix_ui.providers import TriviaSource
    batch = [{"category": "X", "value": 200, "clue": "c", "answer": "a"}]
    asked = []
    online = TriviaSource(CLUES, 1, 1, "/t", questions=3, rng=random.Random(0),
                          fetch_batch=lambda n: asked.append(n) or batch * 5)
    assert online.next_round() == batch * 3 and asked == [3]       # asks for a round's worth, plays only that

    def down(n):
        raise OSError("offline")
    for fetch in (down, lambda n: []):
        offline = TriviaSource(CLUES, 1, 1, "/t", rng=random.Random(0), fetch_batch=fetch)
        assert sorted(c["value"] for c in offline.next_round()) == [200, 400]


def test_trivia_provider_config(tmp_path):
    bank = tmp_path / "c.json"
    bank.write_text(json.dumps(CLUES))
    spec = {"type": "trivia", "mount": "/t", "path": str(bank)}
    assert build_source(spec).fetch_batch is None
    assert build_source({**spec, "provider": "opentdb", "difficulty": "easy", "questions": 10}).fetch_batch is not None
    for extra, message in [({"provider": "jservice"}, "opentdb"), ({"difficulty": "extreme"}, "easy"),
                           ({"questions": 51}, "1 to 50"), ({"questions": 0}, "1 to 50")]:
        with pytest.raises(ConfigError, match=message):
            build_source({**spec, **extra})


def test_trivia_rounds_are_the_requested_size_and_do_not_repeat_until_the_bank_is_used():
    import random
    from matrix_ui.providers import TriviaSource
    bank = [{"category": "C", "value": 100 * i, "clue": f"q{i}", "answer": f"a{i}"} for i in range(1, 8)]
    src = TriviaSource(bank, 1, 1, "/t", questions=3, rng=random.Random(2))
    rounds = [src.next_round() for _ in range(4)]
    assert all(len(r) == 3 for r in rounds)
    for r in rounds:
        assert len({c["value"] for c in r}) == 3                       # no clue twice within a round
    first_seven = [c["value"] for r in rounds[:2] for c in r] + [c["value"] for c in rounds[2][:1]]
    assert sorted(first_seven) == [100, 200, 300, 400, 500, 600, 700]  # the whole bank before any repeat
    assert len(TriviaSource(CLUES, 1, 1, "/t", questions=9).next_round()) == 2      # a small bank caps the round


def test_trivia_source_counts_through_the_round():
    from matrix_ui.providers import TriviaSource
    t = [0.0]
    src = TriviaSource(CLUES, 1, 1, "/trivia", questions=2, tick=0.001,
                       clock=lambda: t.__setitem__(0, t[0] + 0.5) or t[0])
    seen, dm = [], DataModel()
    src.start(dm)
    try:
        assert wait_for(lambda: seen.append(dm.get("/trivia/count_label")) or {"1/2", "2/2"} <= set(seen))
    finally:
        src.stop()


# ---- memoized fetches ----

from matrix_ui.sources import FetchCache


def test_restarted_source_reuses_fresh_data_and_refetches_when_stale():
    cache, calls = FetchCache(), []

    def fetch():
        calls.append(1)
        return {"n": len(calls)}

    def run(interval):
        dm = DataModel()
        src = PollingSource(fetch, interval=interval, mount="/x", key="k", cache=cache).start(dm)
        assert wait_for(lambda: dm.get("/x/n") is not None)
        src.stop()
        return dm.get("/x/n")

    assert run(60) == 1
    assert run(60) == 1 and len(calls) == 1      # fresh: served from the cache, no fetch
    time.sleep(0.05)
    assert run(0.01) == 2 and len(calls) == 2    # stale for this interval: fetched again


def test_stale_value_is_shown_while_refetching():
    cache = FetchCache()
    cache.put("k", {"n": "old"})
    time.sleep(0.02)
    gate = threading.Event()

    def fetch():
        gate.wait(2)
        return {"n": "new"}

    dm = DataModel()
    src = PollingSource(fetch, interval=0.01, mount="/x", key="k", cache=cache).start(dm)
    try:
        assert wait_for(lambda: dm.get("/x/n") == "old")
        gate.set()
        assert wait_for(lambda: dm.get("/x/n") == "new")
    finally:
        src.stop()


def test_sources_with_same_type_and_params_share_a_key():
    a = build_source({"type": "weather", "mount": "/a", "lat": 1, "lon": 2, "interval": 60})
    b = build_source({"type": "weather", "mount": "/b", "lat": 1, "lon": 2, "interval": 300})
    c = build_source({"type": "weather", "mount": "/c", "lat": 1, "lon": 3})
    assert a.key == b.key != c.key


def test_fetch_forecast_now_is_a_rolling_window(monkeypatch):
    import io
    import json as _json
    from datetime import datetime, timedelta, timezone
    from matrix_ui import providers
    now = datetime.now(timezone.utc) - timedelta(hours=4)       # location is UTC-4
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(96)]
    body = {"utc_offset_seconds": -4 * 3600,
            "hourly": {"time": times, "temperature_2m": list(range(96)), "weather_code": list(range(96)),
                       "is_day": [i % 2 for i in range(96)]}}
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda url, timeout: io.StringIO(_json.dumps(body)))
    out = providers.fetch_forecast(1, 2, "now")
    first = times.index(now.strftime("%Y-%m-%dT%H:00"))
    assert [s["code"] for s in out["slots"]] == [first + 3 * i for i in range(6)]
    assert [s["is_day"] for s in out["slots"]] == [bool((first + 3 * i) % 2) for i in range(6)]
    assert [s["hour"] for s in out["slots"]] == [providers.hour_label((now.hour + 3 * i) % 24) for i in range(6)]


def test_train_row_direction_prop():
    from matrix_ui.catalog import REGISTRY
    props = REGISTRY["TrainRow"].props
    assert props["direction"][0]("N") == "N"
    with pytest.raises(ValueError):
        props["direction"][0]("X")


# ---- mta_alerts ----

def _alert(alert_type, routes, text, start=0, end=2_000_000_000):
    return {"alert": {"active_period": [{"start": start, "end": end}],
                      "informed_entity": [{"route_id": r} for r in routes],
                      "header_text": {"translation": [{"text": text, "language": "en"},
                                                      {"text": "<p>html</p>", "language": "en-html"}]},
                      "transit_realtime.mercury_alert": {"alert_type": alert_type}}}


def test_alerts_pick_the_worst_active_alert_per_route():
    from matrix_ui.providers import alerts_from_feed
    feed = {"entity": [
        _alert("Planned - Stops Skipped", ["E", "F"], "E skips 5 Av. Use F instead."),
        _alert("Delays", ["E"], "E trains are delayed. Expect longer waits."),
        _alert("Station Notice", ["7"], "Entrance closed."),
        _alert("Delays", ["7"], "Old delay.", end=100),                      # already over
        _alert("Planned - Part Suspended", ["A"], "A is suspended."),       # not a route we show
    ]}
    out = alerts_from_feed(feed, ["E", "7"], now=1_000_000)
    assert out["E"] == {"label": "Delays", "color": "orange", "headline": "E trains are delayed.", "rank": 3}
    assert out["7"]["label"] == "All clear" and out["7"]["color"] == "green"


def test_alert_types_map_to_labels():
    from matrix_ui.providers import alert_rank
    assert alert_rank("Planned - Part Suspended")[1:] == ("Suspended", "red")
    assert alert_rank("Planned - Reroute")[1:] == ("Svc change", "yellow")
    assert alert_rank("Station Notice") is None


def test_fetch_alerts_adds_headline_and_count(monkeypatch):
    import io
    import json as _json
    from matrix_ui import providers
    feed = {"entity": [_alert("Delays", ["E"], "E is delayed. More later.")]}
    monkeypatch.setattr(providers.urllib.request, "urlopen", lambda req, timeout: io.StringIO(_json.dumps(feed)))
    out = providers.fetch_alerts(["E", "7"])
    assert (out["headline"], out["count"]) == ("E is delayed.", 1)
    feed["entity"] = []
    assert providers.fetch_alerts(["E", "7"])["headline"] == "No service alerts for E, 7."


def test_alerts_source_needs_routes():
    with pytest.raises(ConfigError, match="non-empty list"):
        build_source({"type": "mta_alerts", "mount": "/a", "routes": []})


# ---- daylight ----

def test_daylight_now_by_day_and_by_night():
    from datetime import datetime
    from matrix_ui.providers import daylight_now
    d = lambda day, h, m=0: datetime(2026, 10, day, h, m)
    times = [(d(13, 7, 0), d(13, 18, 0)), (d(14, 7, 0), d(14, 18, 0)), (d(15, 7, 0), d(15, 18, 0))]
    noon = daylight_now(times, d(14, 12, 30))
    assert (noon["phase"], noon["color"], noon["next_label"]) == ("day", "yellow", "Sunset 5h30m")
    assert abs(noon["progress"] - 5.5 / 11) < 1e-9
    assert (noon["sunrise_label"], noon["sunset_label"]) == ("7:00am", "6:00pm")
    night = daylight_now(times, d(14, 21, 0))
    assert (night["phase"], night["color"], night["next_label"]) == ("night", "blue", "Rise 10h00m")
    assert abs(night["progress"] - 3 / 13) < 1e-9


def test_daylight_fetcher_fetches_sun_times_once():
    from datetime import datetime, timedelta
    from matrix_ui.providers import daylight_fetcher
    calls = []
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    pairs = [(today + timedelta(days=i, hours=7), today + timedelta(days=i, hours=18)) for i in (-1, 0, 1)]
    fetch = daylight_fetcher(1, 2, fetch=lambda lat, lon: calls.append(1) or (pairs, 0))
    assert fetch()["phase"] in ("day", "night") and "progress" in fetch()
    assert len(calls) == 1


def test_first_sentence_stops_at_a_line_break_too():
    from matrix_ui.providers import first_sentence
    assert first_sentence("[7] skips 52 St\nAll trains board here.") == "[7] skips 52 St."


# ---- nfl scores ----

def _espn_event(away, home, away_score, home_score, state="in", name="STATUS_IN_PROGRESS", period=3, completed=False,
                date="2026-10-18T17:00Z", clock="7:46"):
    side = lambda abbr, kind, score, color: {"homeAway": kind, "score": str(score),
                                              "team": {"abbreviation": abbr, "color": color, "alternateColor": "000000"}}
    return {"date": date,
            "status": {"period": period, "displayClock": clock,
                       "type": {"name": name, "state": state, "completed": completed}},
            "competitions": [{"competitors": [side(home, "home", home_score, "0000ff"),
                                              side(away, "away", away_score, "ff0000")]}]}


@pytest.mark.parametrize("state, name, period, completed, expected", [
    ("pre", "STATUS_SCHEDULED", 0, False, ("1:05 PM", "", "cyan")),
    ("in", "STATUS_IN_PROGRESS", 1, False, ("Q1", "7:46", "green")),
    ("in", "STATUS_END_PERIOD", 2, False, ("Q2", "7:46", "green")),
    ("in", "STATUS_HALFTIME", 2, False, ("HALF", "", "green")),
    ("in", "STATUS_IN_PROGRESS", 5, False, ("OT", "7:46", "green")),
    ("in", "STATUS_IN_PROGRESS", 6, False, ("2OT", "7:46", "green")),
    ("post", "STATUS_FINAL", 4, True, ("FINAL", "", [150, 150, 150])),
    ("post", "STATUS_FINAL", 5, True, ("F/OT", "", [150, 150, 150])),
    ("in", "STATUS_DELAYED", 2, False, ("DLY", "", "orange")),
    ("post", "STATUS_POSTPONED", 0, False, ("PPD", "", "orange")),
    ("post", "STATUS_SOMETHING_NEW", 0, False, ("ODDLY", "", "orange")),     # unknown, not completed: first five letters
])
def test_nfl_status_labels(state, name, period, completed, expected):
    from datetime import datetime
    from matrix_ui.providers import nfl_status
    status = {"period": period, "displayClock": "7:46",
              "type": {"name": name, "state": state, "completed": completed, "description": "Oddly"}}
    assert nfl_status(status, datetime(2026, 10, 18, 13, 5)) == expected


def test_kickoff_label_fits_a_card_at_any_hour():
    from datetime import datetime
    from matrix_ui.providers import kickoff_label
    at = lambda h, m: kickoff_label(datetime(2026, 10, 18, h, m))
    assert [at(9, 30), at(13, 0), at(20, 20)] == ["9:30 AM", "1:00 PM", "8:20 PM"]
    assert [at(10, 0), at(12, 30), at(0, 5)] == ["10:00AM", "12:30PM", "12:05AM"]      # past 7 characters: no space
    assert all(len(at(h, 45)) <= 7 for h in range(24))


def test_team_accent_keeps_the_hue_and_brightens_dark_team_colours():
    from matrix_ui.providers import GREY, team_accent
    assert team_accent({"color": "0b1c3a", "alternateColor": "e64100"}) == [41, 105, 217]     # Bears navy, lifted to a blue
    assert team_accent({"color": "ffb612", "alternateColor": "000000"}) == [255, 182, 18]     # already bright: unchanged
    assert team_accent({"color": "000000", "alternateColor": "ffb612"}) == [255, 182, 18]     # black: the other colour
    assert max(team_accent({"color": "000000", "alternateColor": "a5acaf"})) >= 216           # silver is lifted too
    for junk in ({}, {"color": "000000"}, {"color": "nothex"}, {"color": None}):
        assert team_accent(junk) == GREY


def test_nfl_game_shows_scores_only_once_started_and_greys_the_team_that_is_behind():
    from datetime import datetime, timezone
    from matrix_ui.providers import GREY, kickoff_label, nfl_game
    pre = nfl_game(_espn_event("CHI", "ATL", 0, 0, state="pre", name="STATUS_SCHEDULED", period=0))
    kickoff = kickoff_label(datetime(2026, 10, 18, 17, 0, tzinfo=timezone.utc).astimezone())      # the machine's clock
    assert pre == {"away": "CHI", "away_score": "", "away_color": "white", "away_accent": [255, 0, 0],
                   "home": "ATL", "home_score": "", "home_color": "white", "home_accent": [0, 0, 255],
                   "label": kickoff, "detail": "", "status_color": "cyan"}
    live = nfl_game(_espn_event("HOU", "JAX", 31, 28, period=4))
    assert (live["away_score"], live["home_score"], live["away_color"], live["home_color"]) == ("31", "28", "white", GREY)
    assert (live["label"], live["detail"], live["status_color"]) == ("Q4", "7:46", "green")
    home_ahead = nfl_game(_espn_event("TEN", "IND", 13, 27, state="post", name="STATUS_FINAL", period=4, completed=True))
    assert (home_ahead["away_color"], home_ahead["home_color"], home_ahead["label"]) == (GREY, "white", "FINAL")
    tied = nfl_game(_espn_event("NYJ", "NE", 17, 17))
    assert (tied["away_color"], tied["home_color"]) == ("white", "white")


def test_fetch_nfl_games_asks_for_the_day_and_orders_by_kickoff(monkeypatch):
    import io
    import json as _json
    from datetime import date
    from matrix_ui import providers
    events = [_espn_event("DAL", "GB", 0, 0, state="pre", name="STATUS_SCHEDULED", period=0, date="2026-10-19T00:20Z"),
              _espn_event("HOU", "JAX", 31, 28, period=4, date="2026-10-18T13:30Z"),
              _espn_event("CHI", "ATL", 0, 0, state="pre", name="STATUS_SCHEDULED", period=0, date="2026-10-18T17:00Z")]
    seen = []
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda url, timeout: seen.append(url) or io.StringIO(_json.dumps({"events": events})))
    games = providers.fetch_nfl_games(date(2026, 10, 18))
    assert "dates=20261018" in seen[0]
    assert [g["away"] for g in games] == ["HOU", "CHI", "DAL"]


def test_nfl_frame_lists_every_game_padded_with_blanks_and_says_how_far_the_rows_reach():
    from datetime import date
    from matrix_ui.providers import BLANK_GAME, nfl_frame
    games = [{**BLANK_GAME, "away": f"T{i}"} for i in range(5)]
    day = date(2026, 10, 5)
    frame = nfl_frame(games, day, 8, 2, 29)
    assert (frame["date_label"], frame["message"]) == ("Oct 5", "")
    assert frame["games"] == games + [BLANK_GAME] * 3           # padded: no card is left without data
    assert frame["length"] == 3 * 29                           # five games in two columns: three rows
    assert nfl_frame(games[:4], day, 8, 2, 29)["length"] == 2 * 29
    assert nfl_frame(games, day, 3, 2, 29)["games"] == games[:3]    # more games than cards: the extras are left off
    assert nfl_frame(games, day, 3, 2, 29)["length"] == 2 * 29
    empty = nfl_frame([], day, 4, 2, 29)
    assert (empty["message"], empty["length"], empty["games"]) == ("No games", 0, [BLANK_GAME] * 4)


def test_nfl_source_publishes_the_games_and_shares_fetches():
    from matrix_ui.providers import NflScoresSource
    cache, calls = FetchCache(), []
    games = [{"away": f"T{i}"} for i in range(3)]

    def fetch(day):
        calls.append(day)
        return games

    def run():
        dm = DataModel()
        src = NflScoresSource("2026-10-18", 4, 2, 29, 60, "/nfl", fetch=fetch, cache=cache).start(dm)
        try:
            assert wait_for(lambda: dm.get("/nfl/length") is not None)
        finally:
            src.stop()
        return dm

    dm = run()
    assert [dm.get(f"/nfl/games/{i}/away") for i in range(3)] == ["T0", "T1", "T2"]
    assert dm.get("/nfl/length") == 2 * 29 and len(dm.get("/nfl/games")) == 4
    assert len(calls) == 1 and calls[0].isoformat() == "2026-10-18"
    run()
    assert len(calls) == 1          # a restarted source reuses the scores while they are fresh


def test_nfl_source_refetches_once_the_scores_are_stale_and_publishes_them_again():
    from matrix_ui.providers import NflScoresSource
    scores = iter([[{"away": "OLD"}], [{"away": "NEW"}]])
    dm = DataModel()
    src = NflScoresSource("2026-10-18", 2, 2, 29, 0.05, "/nfl", fetch=lambda day: next(scores), cache=FetchCache()).start(dm)
    try:
        assert wait_for(lambda: dm.get("/nfl/games/0/away") == "NEW")
    finally:
        src.stop()


def test_nfl_source_keeps_the_last_scores_when_a_fetch_fails_and_does_not_hammer_the_server():
    from matrix_ui.providers import NflScoresSource
    cache, calls = FetchCache(), []

    def fetch(day):
        calls.append(1)
        if len(calls) > 1:
            raise OSError("offline")
        return [{"away": "HOU"}]

    dm = DataModel()
    src = NflScoresSource("2026-10-18", 2, 2, 29, 0.1, "/nfl", fetch=fetch, cache=cache).start(dm)
    try:
        assert wait_for(lambda: len(calls) >= 3, timeout=3)         # it goes on trying, `interval` apart
        time.sleep(0.3)
        assert dm.get("/nfl/games/0/away") == "HOU"                # and the last scores stay on screen
    finally:
        src.stop()
    assert len(calls) <= 12         # about one try per 0.1s, not one per loop

    failing = NflScoresSource("2026-10-18", 2, 2, 29, 60, "/nfl", fetch=lambda day: 1 / 0, cache=FetchCache())
    dm = DataModel()
    failing.start(dm)
    time.sleep(0.1)
    failing.stop()
    assert dm.get("/nfl") is None   # nothing to show yet, so the screen keeps its loading state


def test_nfl_screen_declares_its_source_and_has_a_card_for_every_slot_in_the_grid():
    config = json.load(open(os.path.join(ROOT, "screens", "nfl.json")))
    (source,) = Surface.load(config).sources
    assert (source.mount, source.slots, source.columns, source.row_height) == ("/nfl", 16, 2, 29)
    assert sum(c["component"] == "GameCard" for c in config["components"]) == source.slots
    by_id = {c["id"]: c for c in config["components"]}
    rows = by_id["grid"]["children"]
    assert len(rows) * source.columns == source.slots and all(len(by_id[r]["children"]) == source.columns for r in rows)
    assert source.row_height == card_height(config) + by_id["grid"]["gap"]      # the source's row pitch matches the layout


def card_height(config):
    """Height of a card in the screen's grid: the grid's height shared out among its rows."""
    by_id = {c["id"]: c for c in config["components"]}
    grid = by_id["grid"]
    rows = len(grid["children"])
    return (grid["height"] - grid["gap"] * (rows - 1)) // rows
