import json
import re
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from matrix_ui.model_store import ModelError, ModelStore, validate_model, validate_settings
from matrix_ui.resolver import ConfigError
from serve import PAGE, is_local_address, is_local_host, listen, make_handler, next_firings


@pytest.fixture
def env(tmp_path):
    screens = tmp_path / "screens"
    screens.mkdir()
    for name in ("a", "b"):
        (screens / f"{name}.json").write_text(json.dumps({
            "root": "r", "components": [{"id": "r", "component": "Text", "text": name}],
            "sources": [{"type": "http_json", "mount": "/x", "url": "http://127.0.0.1:9/", "interval": 3600}],
        }))
    config = tmp_path / "matrix.json"
    config.write_text(json.dumps({"power": True, "brightness": 50}))
    return str(config), str(screens)



def make(env):
    config, screens = env
    return ModelStore(config, screens)


def test_undo_restores_previous_model(env):
    a = make(env)
    a.update({"power": False})
    assert json.load(open(env[0]))["power"] is False
    a.undo()
    assert json.load(open(env[0]))["power"] is True
    with pytest.raises(ModelError):
        a.undo()


def test_source_override_validates(env):
    validate_model({"screens": {"a": {"sources": {"/x": {"interval": 99}}}}}, env[1])
    with pytest.raises(ConfigError):
        validate_model({"screens": {"a": {"sources": {"/x": {"interval": "soon"}}}}}, env[1])
    with pytest.raises(ConfigError):
        validate_model({"screens": {"a": {"sources": {"/nope": {"interval": 5}}}}}, env[1])


GOOD_SETTINGS = {
    "power": True, "brightness": 40, "screen": "a",
    "rotation": {"screens": ["a", "b"], "dwell": 10},
    "schedule": [{"screen": "a", "at": "0 */15 * * * *", "for": 15}, {"screen": "b"}],
    "sleep": {"weekday": {"start": "23:30", "end": "05:30"}, "weekend": {"start": "00:00", "end": "08:00"}},
    "screens": {"a": {"sources": {"/x": {"interval": 99}}}},
}


def test_validate_model_accepts_every_documented_key(env):
    validate_model(GOOD_SETTINGS, env[1])
    validate_model({"sleep": {"start": "23:00", "end": "07:00"}}, env[1])
    validate_model({"sleep": {"weekend": {"start": "00:00", "end": "08:00"}}}, env[1])      # no weekday window: fine
    validate_model({}, env[1])


@pytest.mark.parametrize("bad, message", [
    ({"brightnes": 5}, "unknown keys"),
    ({"power": 1}, "power"),
    ({"brightness": 0}, "brightness"),
    ({"brightness": 50.5}, "brightness"),
    ({"brightness": True}, "brightness"),
    ({"screen": 3}, "screen"),
    ({"rotation": {"screens": [], "dwell": 5}}, "rotation.screens"),
    ({"rotation": {"screens": ["a"], "dwell": 0}}, "dwell"),
    ({"rotation": ["a"]}, "rotation"),
    ({"schedule": {"screen": "a"}}, "schedule must be a list"),
    ({"schedule": ["a"]}, "schedule rule 1"),
    ({"schedule": [{"screen": "a"}, {"screen": "b", "at": "61 * * * *"}]}, "schedule rule 2"),
    ({"schedule": [{"screen": "a", "at": ""}]}, "schedule rule 1"),
    ({"schedule": [{"screen": "a", "at": "* * * * *", "for": 0}]}, "for"),
    ({"schedule": [{"screen": "a", "when": "now"}]}, "schedule rule 1"),
    ({"schedule": [{"screen": "nope"}]}, "no screen named 'nope'"),
    ({"sleep": {"start": "25:00", "end": "06:00"}}, "sleep.start"),
    ({"sleep": {"start": "23:00"}}, "sleep.end"),
    ({"sleep": {"weekday": {"start": "22:00", "end": "06:00"}, "start": "01:00"}}, "not both"),
    ({"sleep": "never"}, "sleep"),
    ({"screens": {"a": ["x"]}}, "screens.a"),
    ({"screens": {"a": {"sources": {"/x": 3}}}}, "screens.a"),
    ({"screens": []}, "screens must be an object"),
])
def test_validate_model_rejects_with_a_reason(env, bad, message):
    with pytest.raises(ConfigError, match=message):
        validate_model(bad, env[1])


def test_validate_settings_wants_an_object():
    with pytest.raises(ConfigError):
        validate_settings([])


def test_update_merges_keys_writes_and_undoes(env):
    a = make(env)
    result = a.update({"brightness": 20, "screen": "b"})
    assert result["applied"] and result["reply"] == "Saved."
    assert json.load(open(env[0])) == {"power": True, "brightness": 20, "screen": "b"}
    result = a.update({"screen": None})                     # null removes the key
    assert json.load(open(env[0])) == {"power": True, "brightness": 20}
    assert a.update({"brightness": 20}) == {"reply": "No changes.", "changed": False, "applied": False, "model": result["model"]}
    a.undo()
    assert json.load(open(env[0]))["screen"] == "b"


def test_update_rejects_a_bad_model_and_leaves_the_file_alone(env):
    a = make(env)
    for bad in ({"schedule": [{"screen": "a", "at": "nonsense"}]}, {"screen": "nope"}, {"unknown": 1}, {"brightness": 500}):
        with pytest.raises(ModelError):
            a.update(bad)
    with pytest.raises(ModelError):
        a.update([1])
    assert json.load(open(env[0])) == {"power": True, "brightness": 50}
    with pytest.raises(ModelError):
        a.undo()                                            # nothing was written, so nothing to undo


def test_next_firings_labels_in_local_time():
    now = time.mktime((2026, 1, 5, 10, 7, 30, 0, 0, -1))
    assert next_firings("0 */15 * * * *", 3, now) == ["Mon Jan 05 10:15", "Mon Jan 05 10:30", "Mon Jan 05 10:45"]
    assert next_firings("30 * * * * *", 2, now)[0].endswith("10:08:30")        # seconds shown when they matter
    assert next_firings("0 0 31 2 *", 3, now) == []
    with pytest.raises(ValueError):
        next_firings("not cron", 3, now)


def serve(store, handler=None, extra_hosts=()):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler or make_handler(store, extra_hosts))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def call(url, body=None, method=None, headers=None):
    req = Request(url, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers or {})
    try:
        with urlopen(req) as r:
            return r.status, json.load(r)
    except HTTPError as e:
        return e.code, json.load(e)


def test_http_model(env):
    server, base = serve(make(env))
    try:
        assert call(base + "/health") == (200, {"ok": True})
        assert call(base + "/model")[1]["brightness"] == 50
        assert call(base + "/nope", {})[0] == 404
        assert call(base + "/ask", {"query": "show a"})[0] == 404                           # the Ask endpoint is gone
        assert call(base + "/undo", {}) == (422, {"error": "nothing to undo"})
    finally:
        server.shutdown()


def test_http_patch_model_screens_and_cron(env):
    a = make(env)
    server, base = serve(a)
    try:
        status, body = call(base + "/model", {"brightness": 10, "screen": "b"}, method="PATCH")
        assert status == 200 and body["applied"] and body["model"]["brightness"] == 10
        assert json.load(open(env[0])) == {"power": True, "brightness": 10, "screen": "b"}
        status, body = call(base + "/model", {"schedule": [{"screen": "a", "at": "bad"}]}, method="PATCH")
        assert status == 422 and "schedule rule 1" in body["error"]
        assert call(base + "/model", [1], method="PATCH")[0] == 400
        assert call(base + "/nope", {}, method="PATCH")[0] == 404

        status, body = call(base + "/screens")
        assert status == 200 and sorted(body) == ["a", "b"] and body["a"][0]["mount"] == "/x"

        status, body = call(base + "/cron?at=0%20*/15%20*%20*%20*%20*&count=2")
        assert status == 200 and len(body["next"]) == 2
        assert call(base + "/cron?at=nope")[0] == 400
        assert call(base + "/cron")[0] == 400
        assert call(base + "/cron?at=*%20*%20*%20*%20*&count=x")[0] == 200     # bad count: default
    finally:
        server.shutdown()


def test_listen_binds_every_free_port_and_skips_taken_extras(env):
    handler = make_handler(make(env))
    first, second = listen("127.0.0.1", [0, 0], handler)
    try:
        assert first.server_port != second.server_port
        taken = first.server_port
        (only,) = listen("127.0.0.1", [0, taken], handler)       # the extra is in use: warned about, skipped
        only.server_close()
        with pytest.raises(OSError):
            listen("127.0.0.1", [taken, 0], handler)               # the first port must bind
    finally:
        first.server_close()
        second.server_close()


def test_http_needs_no_credentials(env):
    server, base = serve(make(env))
    try:
        assert call(base + "/model")[0] == 200 and call(base + "/screens")[0] == 200
        assert call(base + "/model", {"brightness": 5}, method="PATCH")[0] == 200
        assert call(base + "/undo", {})[0] == 200
    finally:
        server.shutdown()


def test_http_refuses_writes_from_a_page_on_another_origin(env):
    server, base = serve(make(env))
    try:
        for origin in ("http://evil.example", "http://127.0.0.1:1", "null"):       # other host, other port, sandboxed
            evil = {"Origin": origin}
            assert call(base + "/model", {"brightness": 5}, method="PATCH", headers=evil)[0] == 403
            assert call(base + "/undo", {}, headers=evil)[0] == 403
        assert json.load(open(env[0])) == {"power": True, "brightness": 50}     # nothing got through
        assert call(base + "/model", headers={"Origin": "http://evil.example"})[0] == 200    # reads are only data for them
        same = {"Origin": f"http://127.0.0.1:{server.server_port}"}              # the page this service serves
        assert call(base + "/model", {"brightness": 5}, method="PATCH", headers=same)[0] == 200
        assert call(base + "/model", {"brightness": 6}, method="PATCH")[0] == 200              # no Origin: curl, scripts
    finally:
        server.shutdown()


def test_http_serves_the_page(env):
    server, base = serve(make(env))
    try:
        with urlopen(base + "/") as r:
            page = r.read().decode()
            assert r.status == 200 and r.headers["Content-Type"].startswith("text/html")
            assert "default-src 'none'" in r.headers["Content-Security-Policy"]        # the page may only talk to this service
            assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "<title>LED Matrix</title>" in page
    finally:
        server.shutdown()


def test_the_page_loads_nothing_from_elsewhere():
    page = open(PAGE).read()
    assert not re.search(r"""(?:src|href|action)\s*=\s*["']?\s*(?:https?:)?//""", page)
    assert not re.search(r"@import|url\(\s*[\"']?(?:https?:)?//|\bimport\s*\(|\bWebSocket\b|\bEventSource\b", page)
    assert not re.search(r"fetch\(\s*[\"'`]\s*(?:https?:)?//", page)           # every fetch goes to this service


# ---- local network only ----

@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "192.168.1.5", "10.0.0.1", "172.16.5.5", "169.254.1.1",
                                  "fe80::1%eth0", "fd12:3456::1", "::ffff:192.168.1.5"])
def test_local_addresses(addr):
    assert is_local_address(addr)


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "100.64.0.1", "172.32.0.1", "2001:4860:4860::8888", "::ffff:8.8.8.8",
                                  "not an address", ""])
def test_other_addresses_are_not_local(addr):
    assert not is_local_address(addr)


@pytest.mark.parametrize("host", ["127.0.0.1:8099", "[::1]:8099", "192.168.1.5", "localhost:8099", "raspberrypi", "raspberrypi:80",
                                  "raspberrypi.local", "Raspberrypi.LOCAL:80", "pi.lan", "pi.home.arpa", "8.8.8.8"])
def test_local_host_names(host):
    assert is_local_host(host)


@pytest.mark.parametrize("host", [None, "", "evil.example", "evil.example:8099", "attacker.com.", "localhost.evil.com",
                                  "pi.local.evil.com", "1.2.3.4.evil.com", "[::1", "evil.example:notaport"])
def test_other_host_names_are_not_local(host):
    assert not is_local_host(host)


def test_allowed_hosts_extend_the_local_names():
    assert not is_local_host("pi.fritz.box")
    assert is_local_host("pi.fritz.box:80", ("pi.fritz.box",))


def test_http_refuses_a_host_name_that_is_not_local(env):
    """What DNS rebinding looks like: the browser is on the LAN, but the page's own domain now points at the Pi."""
    server, base = serve(make(env), extra_hosts=("pi.fritz.box",))
    try:
        for path in ("/", "/health", "/model", "/screens"):
            rebound = urlopen_status(base + path, {"Host": "evil.example"})
            assert rebound == 403, path
        assert call(base + "/model", {"brightness": 5}, method="PATCH", headers={"Host": "evil.example"})[0] == 403
        assert call(base + "/undo", {}, headers={"Host": "evil.example", "Origin": "http://evil.example"})[0] == 403
        assert json.load(open(env[0])) == {"power": True, "brightness": 50}
        status, body = call(base + "/model", headers={"Host": "evil.example"})
        assert "MATRIX_ALLOWED_HOSTS" in body["error"]
        assert call(base + "/model", headers={"Host": "pi.fritz.box"})[0] == 200
        assert call(base + "/model", headers={"Host": "raspberrypi.local"})[0] == 200
    finally:
        server.shutdown()


def urlopen_status(url, headers):
    try:
        with urlopen(Request(url, headers=headers)) as r:
            return r.status
    except HTTPError as e:
        return e.code


def test_http_refuses_requests_that_came_through_a_proxy_or_tunnel(env):
    """cloudflared, ngrok, tailscale serve or nginx on the Pi connect from 127.0.0.1 and add forwarding headers."""
    server, base = serve(make(env))
    try:
        for header in ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP"):
            assert urlopen_status(base + "/model", {header: "203.0.113.9"}) == 403, header
            assert call(base + "/model", {"brightness": 5}, method="PATCH", headers={header: "x"})[0] == 403, header
        assert urlopen_status(base + "/", {"x-forwarded-for": "8.8.8.8"}) == 403               # any capitalisation
        assert json.load(open(env[0])) == {"power": True, "brightness": 50}
        assert call(base + "/model")[0] == 200                                                 # the same call without it
    finally:
        server.shutdown()


def test_http_refuses_a_client_from_outside_the_local_network(env):
    """A port forward or tunnel on the router shows up as a public source address."""
    class FromAbroad(make_handler(make(env))):
        @property
        def client_address(self):
            return ("8.8.8.8", 5555)

        @client_address.setter
        def client_address(self, value):
            pass

    server, base = serve(None, handler=FromAbroad)
    try:
        for path in ("/", "/health", "/model"):
            assert urlopen_status(base + path, {}) == 403, path
        assert call(base + "/model", {"brightness": 5}, method="PATCH")[0] == 403
        assert call(base + "/undo", {})[0] == 403
        assert json.load(open(env[0])) == {"power": True, "brightness": 50}
    finally:
        server.shutdown()
