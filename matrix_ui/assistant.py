"""Natural-language control of the global model.

`Assistant.ask("show the weather and dim it")` sends the query, the current global model and a description of
the available screens to Claude (through the Claude Code CLI), gets back a patch (structured output), applies it to a copy of the model,
validates the result the way the runner will load it, and only then writes the model file, which `run.py`
reloads. A rejected patch is sent back to Claude once with the error; if it still fails nothing is written.
"""
import copy
import glob
import json
import os
import subprocess
import tempfile
import threading
from types import SimpleNamespace

from .app import load_surface
from .resolver import ConfigError

DEFAULT_MODEL = "claude-opus-5-5"
HISTORY = 10                    # how many previous models `undo` can step back through

# Structured-output schema. Every field is required; null means "leave this alone".
PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "power": {"type": ["boolean", "null"]},
        "brightness": {"type": ["integer", "null"]},
        "screen": {"type": ["string", "null"]},
        "rotation": {"anyOf": [
            {"type": "null"},
            {"type": "object",
             "properties": {"screens": {"type": "array", "items": {"type": "string"}}, "dwell": {"type": "integer"}},
             "required": ["screens", "dwell"], "additionalProperties": False},
        ]},
        "source_changes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "screen": {"type": "string"},
                "mount": {"type": "string"},
                "params_json": {"type": "string"},
                "reset": {"type": "boolean"},
            },
            "required": ["screen", "mount", "params_json", "reset"], "additionalProperties": False,
        }},
    },
    "required": ["reply", "power", "brightness", "screen", "rotation", "source_changes"],
    "additionalProperties": False,
}

SYSTEM = """You control a 64x64 LED matrix by editing its global model. Given the user's request and the current \
model, return a patch.

Patch fields (null means leave unchanged):
- power: false blanks the matrix, true turns it on.
- brightness: integer 1-100.
- screen: pin one screen by name; "" unpins it so the rotation resumes. A pinned screen wins over the rotation.
- rotation: {{"screens": [names], "dwell": seconds per screen}}, replacing the whole rotation.
- source_changes: a list of {{screen, mount, params_json, reset}}. params_json is a JSON object string of source \
params merged over that screen's source at `mount` (e.g. {{"symbol": "AAPL"}}); only use params and values listed for \
that source. reset=true removes the override for that mount (params_json then "{{}}"). Overrides persist, so a later \
change to the same mount only needs the params that change.
- reply: one short sentence, plain text, saying what you did or answering the question. It may be spoken aloud.

Only use screens and source mounts from the list below. If the request can't be done with these controls, change \
nothing (all null, empty source_changes) and say why in reply. If it is a question, answer it from the model.

Available screens and their data sources (defaults from the screen files):
{screens}
"""


class AskError(Exception):
    """The request could not be turned into a valid model."""


def describe_screens(screens_dir):
    """{name: [source specs]} for every screen file in the directory."""
    out = {}
    for path in sorted(glob.glob(os.path.join(screens_dir, "*.json"))):
        name = os.path.basename(path)[:-5]
        if name.endswith((".sample_data", ".clues")):
            continue
        try:
            with open(path) as f:
                config = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(config, dict) and "components" in config:
            out[name] = config.get("sources", [])
    return out


def apply_patch(model, patch):
    """A copy of `model` with the patch applied. Raises ConfigError on a malformed patch."""
    new = copy.deepcopy(model)
    if patch.get("power") is not None:
        new["power"] = bool(patch["power"])
    if patch.get("brightness") is not None:
        b = patch["brightness"]
        if not 1 <= b <= 100:
            raise ConfigError(f"brightness must be 1-100, got {b}")
        new["brightness"] = b
    if patch.get("screen") is not None:
        if patch["screen"] == "":
            new.pop("screen", None)
        else:
            new["screen"] = patch["screen"]
    if patch.get("rotation") is not None:
        rot = patch["rotation"]
        if not rot["screens"]:
            raise ConfigError("rotation needs at least one screen")
        if rot["dwell"] < 1:
            raise ConfigError("rotation dwell must be at least 1 second")
        new["rotation"] = {"screens": list(rot["screens"]), "dwell": rot["dwell"]}
    for change in patch.get("source_changes") or []:
        screen, mount = change["screen"], change["mount"]
        sources = new.setdefault("screens", {}).setdefault(screen, {}).setdefault("sources", {})
        if change["reset"]:
            sources.pop(mount, None)
        else:
            try:
                params = json.loads(change["params_json"])
            except ValueError as e:
                raise ConfigError(f"params_json for {screen} {mount} isn't valid JSON: {e}")
            if not isinstance(params, dict):
                raise ConfigError(f"params_json for {screen} {mount} must be a JSON object")
            sources.setdefault(mount, {}).update(params)
        if not sources:
            del new["screens"][screen]["sources"]
        if not new["screens"][screen]:
            del new["screens"][screen]
    if not new.get("screens"):
        new.pop("screens", None)
    return new


def validate_model(model, screens_dir):
    """Load every screen the model names, with its overrides, so a bad name or param fails before it is written."""
    names = set((model.get("screens") or {}))
    if model.get("screen"):
        names.add(model["screen"])
    names.update((model.get("rotation") or {}).get("screens") or [])
    for name in sorted(names):
        overrides = ((model.get("screens") or {}).get(name) or {}).get("sources") or {}
        try:
            load_surface(screens_dir, name, overrides)
        except FileNotFoundError:
            raise ConfigError(f"no screen named {name!r}")
        except (OSError, ValueError) as e:     # ConfigError is a ValueError
            raise ConfigError(f"{name}: {e}")


class CliClient:
    """Asks Claude by running a script that calls the Claude Code CLI (uses its login; no API key).

    `script` gets the system prompt and schema as file arguments and the conversation on stdin, and prints the
    patch JSON. See scripts/claude-propose.sh.
    """

    def __init__(self, script="scripts/claude-propose.sh", timeout=120):
        self.script, self.timeout = script, timeout
        self.messages = self

    def create(self, system, messages, output_config, **_):
        with tempfile.TemporaryDirectory() as tmp:
            system_file, schema_file = os.path.join(tmp, "system.txt"), os.path.join(tmp, "schema.json")
            with open(system_file, "w") as f:
                f.write(system)
            with open(schema_file, "w") as f:
                json.dump(output_config["format"]["schema"], f)
            try:
                run = subprocess.run([self.script, system_file, schema_file], input=self._transcript(messages),
                                     capture_output=True, text=True, timeout=self.timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise AskError(f"claude CLI failed: {e}")
        if run.returncode != 0:
            raise AskError(f"claude CLI failed: {run.stderr.strip()[:300]}")
        block = SimpleNamespace(type="text", text=run.stdout.strip())
        return SimpleNamespace(stop_reason="end_turn", content=[block])

    @staticmethod
    def _transcript(messages):
        """One prompt from the message list; a retry carries the rejected answer and the error."""
        if len(messages) == 1:
            return messages[0]["content"]
        parts = []
        for m in messages:
            text = m["content"] if isinstance(m["content"], str) else "".join(b.text for b in m["content"] if b.type == "text")
            parts.append(f"{'Assistant' if m['role'] == 'assistant' else 'User'}: {text}")
        return "\n\n".join(parts)


class Assistant:
    def __init__(self, config_path="matrix.json", screens_dir="screens", client=None, model=None):
        self.config_path = config_path
        self.screens_dir = screens_dir
        self.client = client or CliClient()
        self.model_name = model or os.environ.get("MATRIX_AI_MODEL") or DEFAULT_MODEL
        self._history = []
        self._lock = threading.Lock()

    # ---- model file ----

    def read(self):
        try:
            with open(self.config_path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _write(self, model):
        tmp = self.config_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(model, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.config_path)       # atomic, so the runner never reads a half-written file

    # ---- asking ----

    def ask(self, query, dry_run=False):
        """Apply `query` to the model. Returns {reply, changed, applied, model}; raises AskError."""
        with self._lock:
            current = self.read()
            messages = [{"role": "user", "content": f"Current model:\n{json.dumps(current, indent=2)}\n\nRequest: {query}"}]
            for attempt in (1, 2):
                patch, content = self._propose(messages)
                try:
                    new = apply_patch(current, patch)
                    validate_model(new, self.screens_dir)
                    break
                except ConfigError as e:
                    if attempt == 2:
                        raise AskError(f"couldn't apply that: {e}")
                    messages += [{"role": "assistant", "content": content},
                                 {"role": "user", "content": f"That patch was rejected: {e}. Return a corrected patch."}]
            changed = new != current
            if changed and not dry_run:
                self._history = (self._history + [current])[-HISTORY:]
                self._write(new)
            return {"reply": patch["reply"], "changed": changed, "applied": changed and not dry_run, "model": new}

    def undo(self):
        with self._lock:
            if not self._history:
                raise AskError("nothing to undo")
            self._write(self._history.pop())
            return {"reply": "Undone.", "changed": True, "applied": True, "model": self.read()}

    def _propose(self, messages):
        screens = json.dumps(describe_screens(self.screens_dir), indent=1)
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=4000,
            system=SYSTEM.format(screens=screens),
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": PATCH_SCHEMA}},
            messages=messages,
        )
        if response.stop_reason == "refusal":
            raise AskError("the AI declined that request")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if response.stop_reason == "max_tokens" or text is None:
            raise AskError("the AI gave no usable answer")
        try:
            return json.loads(text), response.content
        except ValueError:
            raise AskError("the AI answer wasn't valid JSON")
