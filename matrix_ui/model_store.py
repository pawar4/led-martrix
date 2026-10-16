"""The global model file (`matrix.json`) for writers: validated edits and one-step undo.

`ModelStore.update({"brightness": 20})` merges top-level keys into the model, validates the result the way the runner
will load it (`validate_model`), and only then writes the file, which `run.py` reloads. `undo()` steps back through the
last few models. Used by `serve.py`, the web page's back end. Nothing here touches the network.
"""
import glob
import json
import os
import threading

from .app import _minutes, load_surface
from .cron import Cron
from .resolver import ConfigError

HISTORY = 10                    # how many previous models `undo` can step back through
MODEL_KEYS = {"power", "brightness", "sleep", "screen", "schedule", "rotation", "screens"}


class ModelError(Exception):
    """The change could not be turned into a valid model."""


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


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_window(window, where):
    if not isinstance(window, dict):
        raise ConfigError(f"{where} must be an object with start and end")
    for key in ("start", "end"):
        try:
            _minutes(window[key])
        except (KeyError, TypeError, ValueError):
            raise ConfigError(f'{where}.{key} must be a time like "23:30"')


def validate_settings(model):
    """Check the shape of the model strictly. The runner skips what it can't read; a write should say why instead."""
    if not isinstance(model, dict):
        raise ConfigError("the model must be a JSON object")
    if set(model) - MODEL_KEYS:
        raise ConfigError(f"unknown keys {sorted(set(model) - MODEL_KEYS)}; expected some of {sorted(MODEL_KEYS)}")
    if "power" in model and not isinstance(model["power"], bool):
        raise ConfigError("power must be true or false")
    if "brightness" in model:
        b = model["brightness"]
        if isinstance(b, bool) or not isinstance(b, int) or not 1 <= b <= 100:
            raise ConfigError("brightness must be an integer from 1 to 100")
    if "screen" in model and not isinstance(model["screen"], str):
        raise ConfigError("screen must be a screen name")
    if "rotation" in model:
        rot = model["rotation"]
        if not isinstance(rot, dict) or set(rot) - {"screens", "dwell"}:
            raise ConfigError('rotation must be {"screens": [...], "dwell": seconds}')
        names = rot.get("screens")
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ConfigError("rotation.screens must be a non-empty list of screen names")
        if "dwell" in rot and not (_number(rot["dwell"]) and rot["dwell"] >= 1):
            raise ConfigError("rotation.dwell must be at least 1 second")
    if "schedule" in model:
        if not isinstance(model["schedule"], list):
            raise ConfigError("schedule must be a list of rules")
        for i, rule in enumerate(model["schedule"], 1):
            where = f"schedule rule {i}"
            if not isinstance(rule, dict) or set(rule) - {"screen", "at", "for"}:
                raise ConfigError(f'{where} must be {{"screen", "at"?, "for"?}}')
            if not isinstance(rule.get("screen"), str) or not rule["screen"]:
                raise ConfigError(f"{where} needs a screen name")
            if "at" in rule:
                try:
                    if not isinstance(rule["at"], str) or not rule["at"].strip():
                        raise ValueError
                    Cron(rule["at"])
                except ValueError:
                    raise ConfigError(f"{where}: {rule['at']!r} isn't a cron expression "
                                      "(5 fields, or 6 with leading seconds)")
            if "for" in rule and not (_number(rule["for"]) and rule["for"] > 0):
                raise ConfigError(f"{where}: for must be a positive number of seconds")
    if "sleep" in model:
        sleep = model["sleep"]
        if isinstance(sleep, dict) and ("weekday" in sleep or "weekend" in sleep):
            if set(sleep) - {"weekday", "weekend"}:
                raise ConfigError("sleep takes either start/end or weekday/weekend, not both")
            for day in sleep:
                _check_window(sleep[day], f"sleep.{day}")
        else:
            _check_window(sleep, "sleep")
    screens = model.get("screens", {})
    if not isinstance(screens, dict):
        raise ConfigError("screens must be an object")
    for name, config in screens.items():
        sources = config.get("sources", {}) if isinstance(config, dict) and set(config) <= {"sources"} else None
        if not isinstance(sources, dict) or not all(isinstance(v, dict) for v in sources.values()):
            raise ConfigError(f'screens.{name} must be {{"sources": {{mount: {{param: value}}}}}}')


def validate_model(model, screens_dir):
    """Check the model's shape, then load every screen it names, with its overrides, so a bad name or param fails
    before it is written."""
    validate_settings(model)
    names = set(model.get("screens") or {})
    if model.get("screen"):
        names.add(model["screen"])
    names.update((model.get("rotation") or {}).get("screens") or [])
    names.update(rule["screen"] for rule in model.get("schedule") or [])
    for name in sorted(names):
        overrides = ((model.get("screens") or {}).get(name) or {}).get("sources") or {}
        try:
            load_surface(screens_dir, name, overrides)
        except FileNotFoundError:
            raise ConfigError(f"no screen named {name!r}")
        except (OSError, ValueError) as e:     # ConfigError is a ValueError
            raise ConfigError(f"{name}: {e}")



class ModelStore:
    def __init__(self, config_path="matrix.json", screens_dir="screens"):
        self.config_path = config_path
        self.screens_dir = screens_dir
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

    # ---- editing ----

    def update(self, changes):
        """Merge top-level keys into the model (a null value removes the key), validate and write. Returns
        {reply, changed, applied, model}; raises ModelError when the result isn't a valid model."""
        if not isinstance(changes, dict):
            raise ModelError("changes must be a JSON object of top-level keys")
        with self._lock:
            current = self.read()
            new = {**current, **changes}
            for key in [k for k, v in new.items() if v is None]:
                del new[key]
            try:
                validate_model(new, self.screens_dir)
            except ConfigError as e:
                raise ModelError(str(e))
            changed = new != current
            if changed:
                self._history = (self._history + [current])[-HISTORY:]
                self._write(new)
            return {"reply": "Saved." if changed else "No changes.", "changed": changed, "applied": changed, "model": new}

    def undo(self):
        with self._lock:
            if not self._history:
                raise ModelError("nothing to undo")
            self._write(self._history.pop())
            return {"reply": "Undone.", "changed": True, "applied": True, "model": self.read()}
