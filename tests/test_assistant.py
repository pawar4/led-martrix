import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from matrix_ui.assistant import Assistant, AskError, apply_patch, validate_model
from matrix_ui.resolver import ConfigError
from serve import make_handler


def patch(**kw):
    base = {"reply": "ok", "power": None, "brightness": None, "screen": None, "rotation": None, "source_changes": []}
    base.update(kw)
    return base


class FakeClient:
    """Returns the queued patches in order, recording each request."""

    def __init__(self, *patches):
        self.patches, self.calls = list(patches), []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.patches.pop(0)))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


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


def make(env, *patches):
    config, screens = env
    return Assistant(config, screens, client=FakeClient(*patches), model="m")


def test_ask_applies_and_writes_model(env):
    a = make(env, patch(screen="b", brightness=20, reply="Showing b."))
    result = a.ask("show b dimly")
    assert result["applied"] and result["reply"] == "Showing b."
    assert json.load(open(env[0])) == {"power": True, "brightness": 20, "screen": "b"}


def test_dry_run_does_not_write(env):
    a = make(env, patch(screen="b"))
    result = a.ask("show b", dry_run=True)
    assert result["changed"] and not result["applied"] and result["model"]["screen"] == "b"
    assert "screen" not in json.load(open(env[0]))


def test_no_change_for_a_question(env):
    a = make(env, patch(reply="Brightness is 50."))
    result = a.ask("how bright is it?")
    assert not result["changed"] and result["reply"] == "Brightness is 50."


def test_invalid_patch_is_retried_with_the_error(env):
    a = make(env, patch(screen="nope"), patch(screen="a"))
    assert a.ask("show a")["applied"]
    retry = a.client.calls[1]["messages"]
    assert "no screen named 'nope'" in retry[-1]["content"]
    assert json.load(open(env[0]))["screen"] == "a"


def test_gives_up_after_one_retry_and_leaves_file_alone(env):
    a = make(env, patch(screen="nope"), patch(screen="nope"))
    with pytest.raises(AskError):
        a.ask("show nope")
    assert json.load(open(env[0])) == {"power": True, "brightness": 50}


def test_undo_restores_previous_model(env):
    a = make(env, patch(power=False))
    a.ask("turn it off")
    assert json.load(open(env[0]))["power"] is False
    a.undo()
    assert json.load(open(env[0]))["power"] is True
    with pytest.raises(AskError):
        a.undo()


def test_source_override_merges_validates_and_resets(env):
    model = {}
    change = {"screen": "a", "mount": "/x", "params_json": '{"interval": 99}', "reset": False}
    model = apply_patch(model, patch(source_changes=[change]))
    assert model == {"screens": {"a": {"sources": {"/x": {"interval": 99}}}}}
    validate_model(model, env[1])
    reset = {"screen": "a", "mount": "/x", "params_json": "{}", "reset": True}
    assert apply_patch(model, patch(source_changes=[reset])) == {}
    with pytest.raises(ConfigError):
        validate_model({"screens": {"a": {"sources": {"/x": {"interval": "soon"}}}}}, env[1])
    with pytest.raises(ConfigError):
        validate_model({"screens": {"a": {"sources": {"/nope": {"interval": 5}}}}}, env[1])


def test_apply_patch_rejects_bad_values():
    with pytest.raises(ConfigError):
        apply_patch({}, patch(brightness=500))
    with pytest.raises(ConfigError):
        apply_patch({}, patch(rotation={"screens": [], "dwell": 5}))
    with pytest.raises(ConfigError):
        apply_patch({}, patch(source_changes=[{"screen": "a", "mount": "/x", "params_json": "[1]", "reset": False}]))


def test_empty_screen_unpins():
    assert apply_patch({"screen": "a", "power": True}, patch(screen="")) == {"power": True}


def serve(assistant, token=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(assistant, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def call(url, body=None, token=None):
    req = Request(url, data=None if body is None else json.dumps(body).encode(),
                  headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urlopen(req) as r:
            return r.status, json.load(r)
    except HTTPError as e:
        return e.code, json.load(e)


def test_http_ask_model_and_auth(env):
    a = make(env, patch(screen="a", reply="Done."))
    server, base = serve(a, token="s3cret")
    try:
        assert call(base + "/health")[0] == 200
        assert call(base + "/model")[0] == 401
        status, body = call(base + "/ask", {"query": "show a"}, token="s3cret")
        assert status == 200 and body["reply"] == "Done." and body["applied"]
        assert call(base + "/model", token="s3cret")[1]["screen"] == "a"
        assert call(base + "/ask", {"query": ""}, token="s3cret")[0] == 400
        assert call(base + "/nope", {}, token="s3cret")[0] == 404
    finally:
        server.shutdown()


def test_http_ai_failure_is_422(env):
    a = make(env, patch(screen="nope"), patch(screen="nope"))
    server, base = serve(a)
    try:
        status, body = call(base + "/ask", {"query": "x"})
        assert status == 422 and "nope" in body["error"]
    finally:
        server.shutdown()


def test_cli_client_runs_the_script_and_reads_its_stdout(tmp_path, env):
    from matrix_ui.assistant import CliClient
    script = tmp_path / "fake.sh"
    script.write_text('#!/bin/sh\ncat "$2" >/dev/null; cat >/dev/null; echo \'{"reply":"hi","power":false,"brightness":null,'
                      '"screen":null,"rotation":null,"source_changes":[]}\'\n')
    script.chmod(0o755)
    a = Assistant(env[0], env[1], client=CliClient(str(script)), model="m")
    result = a.ask("turn it off")
    assert result["reply"] == "hi" and json.load(open(env[0]))["power"] is False


def test_cli_client_script_failure_is_an_ask_error(tmp_path, env):
    from matrix_ui.assistant import CliClient
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
    script.chmod(0o755)
    a = Assistant(env[0], env[1], client=CliClient(str(script)), model="m")
    with pytest.raises(AskError, match="boom"):
        a.ask("x")
