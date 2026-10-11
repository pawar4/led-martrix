import json
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
    assert sorted(s.mount for s in surface.sources) == ["/trains", "/weather"]


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
    ({"type": "mta_arrivals", "mount": "/t", "stations": {"E": {"stop_id": "F09"}}}, "exactly"),
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
