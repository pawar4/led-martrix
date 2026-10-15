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


def test_schedule_interleaves_screens_on_wall_clock(tmp_path):
    t = [0]
    m = DataModel({"app": {"schedule": {"default": "a", "every": 900, "screens": ["b", "c"], "duration": 15},
                           "rotation": {"screens": ["a"], "dwell": 5}}})
    app = make_app(tmp_path, m)
    app._wall = lambda: t[0]
    assert [_at(app, t, x) for x in (0, 14, 15, 29, 30, 899, 900, 915)] == ["b", "b", "c", "c", "a", "a", "b", "c"]


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
