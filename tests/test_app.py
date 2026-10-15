import json

from matrix_ui import App, DataModel


def make_app(tmp_path, model, clock=lambda: 0):
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "root": "r", "components": [{"id": "r", "component": "Text", "text": name}],
            "sources": [{"type": "http_json", "mount": "/x", "url": "http://127.0.0.1:9/", "interval": 3600}],
        }))
    return App(model, str(tmp_path), clock=clock)


def test_pinned_screen_wins_over_rotation(tmp_path):
    m = DataModel({"app": {"screen": "b", "rotation": {"screens": ["a"], "dwell": 5}}})
    app = make_app(tmp_path, m)
    app.update()
    assert app.active == "b" and m.get("/status/active") == "b"


def test_rotation_advances_after_dwell(tmp_path):
    t = [0]
    m = DataModel({"app": {"rotation": {"screens": ["a", "b"], "dwell": 10}}})
    app = make_app(tmp_path, m, clock=lambda: t[0])
    app.update()
    assert app.active == "a"
    t[0] = 9
    app.update()
    assert app.active == "a"
    t[0] = 10
    app.update()
    assert app.active == "b"
    t[0] = 20
    app.update()
    assert app.active == "a"


def test_schedule_first_matching_rule_wins(tmp_path):
    t = [0]
    m = DataModel({"app": {"schedule": [
        {"screen": "b", "at": "0 */15 * * * *", "for": 15},
        {"screen": "c", "at": "15 */15 * * * *", "for": 15},
        {"screen": "a"}],
        "rotation": {"screens": ["a"], "dwell": 5}}})
    app = make_app(tmp_path, m)
    base = at(10, 0)
    app._wall = lambda: base + t[0]
    assert [_at(app, t, x) for x in (0, 14, 15, 29, 30, 899, 900, 915)] == ["b", "b", "c", "c", "a", "a", "b", "c"]


def test_schedule_cron_days_and_fallbacks(tmp_path):
    t = [0]
    rules = [{"screen": "b", "at": "30 9 * * 1-5", "for": 3600},           # weekdays 09:30 for an hour
             {"screen": "c", "at": "bogus"}, {"screen": "c", "at": "* * * * *", "for": -1}]
    m = DataModel({"app": {"schedule": rules}})
    app = make_app(tmp_path, m)
    app._wall = lambda: t[0]
    assert _at(app, t, at(9, 30)) == "b"                # Monday
    assert _at(app, t, at(10, 29, 59)) == "b"
    assert _at(app, t, at(10, 30)) is None              # no fallback rule: rotation/None
    assert _at(app, t, at(9, 29)) is None
    assert _at(app, t, at(9, 30) + 5 * 86400) is None   # Saturday


def _at(app, t, now):
    t[0] = now
    return app.desired()


def test_power_off_stops_screen(tmp_path):
    m = DataModel({"app": {"screen": "a"}})
    app = make_app(tmp_path, m)
    app.update()
    m.set("/app/power", False)
    app.update()
    assert app.active is None and m.get("/status/active") is None


def test_missing_screen_keeps_current_and_reports(tmp_path):
    m = DataModel({"app": {"screen": "a"}})
    app = make_app(tmp_path, m)
    app.update()
    m.set("/app/screen", "nope")
    app.update()
    assert app.active == "a" and "nope" in m.get("/status/error")


def test_source_override_reloads_screen_and_is_validated(tmp_path):
    m = DataModel({"app": {"screen": "a"}})
    app = make_app(tmp_path, m)
    app.update()
    first = app._surface
    m.set("/app/screens/a/sources", {"/x": {"interval": 7}})
    app.update()
    assert app._surface is not first and app.active == "a"
    assert app._surface.sources[0].interval == 7
    m.set("/app/screens/a/sources", {"/x": {"bogus": 1}})
    app.update()
    assert "bogus" in m.get("/status/error") and app.active == "a"
    m.set("/app/screens/a/sources", {"/nope": {}})
    app.update()
    assert "/nope" in m.get("/status/error")


def test_brightness_clamped_and_validated():
    app = App(DataModel({"app": {"brightness": 500}}))
    assert app.brightness() == 100
    app.model.set("/app/brightness", "x")
    assert app.brightness() is None


def at(hour, minute=0, second=0):
    import time
    return time.mktime((2026, 1, 5, hour, minute, second, 0, 0, -1))


def test_sleep_window_spanning_midnight(tmp_path):
    m = DataModel({"app": {"screen": "a", "brightness": 40, "sleep": {"start": "23:00", "end": "07:00"}}})
    app = make_app(tmp_path, m)
    app._wall = lambda: at(23, 30)
    app.update()
    assert app.asleep() and app.brightness() == 0 and app.active is None
    app._wall = lambda: at(6, 59)
    assert app.asleep()
    app._wall = lambda: at(7)
    app.update()
    assert not app.asleep() and app.brightness() == 40 and app.active == "a"


def test_sleep_window_same_day_and_invalid(tmp_path):
    app = make_app(tmp_path, DataModel({"app": {"sleep": {"start": "01:00", "end": "05:00"}}}))
    app._wall = lambda: at(3)
    assert app.asleep()
    app._wall = lambda: at(12)
    assert not app.asleep()
    for bad in ({"start": "x", "end": "07:00"}, {"start": "25:00", "end": "07:00"}, {"start": "07:00"}, "no"):
        app.model.set("/app/sleep", bad)
        app._wall = lambda: at(3)
        assert not app.asleep()


def test_sleep_weekday_and_weekend_windows(tmp_path):
    sleep = {"weekday": {"start": "23:00", "end": "06:30"}, "weekend": {"start": "00:00", "end": "09:00"}}
    app = make_app(tmp_path, DataModel({"app": {"sleep": sleep}}))
    at_day = lambda day, h, m=0: __import__("time").mktime((2026, 1, day, h, m, 0, 0, 0, -1))   # Jan 5 2026 is Monday
    app._wall = lambda: at_day(5, 8)
    assert not app.asleep()                 # Monday 08:00
    app._wall = lambda: at_day(5, 6)
    assert app.asleep()                     # Monday 06:00
    app._wall = lambda: at_day(10, 8)
    assert app.asleep()                     # Saturday 08:00
    app._wall = lambda: at_day(10, 9)
    assert not app.asleep()
    app.model.set("/app/sleep", {"weekend": sleep["weekend"]})
    app._wall = lambda: at_day(6, 3)
    assert not app.asleep()                 # Tuesday has no window
