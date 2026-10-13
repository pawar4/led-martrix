"""The global model: one DataModel that decides which screen runs and how it is configured.

Model layout (`/app` is the control state, loaded from a JSON file and reloaded when it changes):

  /app/power        false blanks the matrix (default true)
  /app/brightness   1-100
  /app/screen       pin this screen by name; wins over the rotation
  /app/rotation     {"screens": ["subway", "weather"], "dwell": 20}   dwell is seconds per screen
  /app/screens/<name>/sources/<mount>   {param: value}, merged over that screen's source of that mount

`/status` is written by the App itself (`/status/active`, `/status/error`) and never by the file.
Each screen keeps its own DataModel for its data, so screens can't clobber each other's paths.
"""
import json
import logging
import os
import time

from .datamodel import DataModel
from .resolver import ConfigError, Surface
from .sources import StaticFileSource

log = logging.getLogger(__name__)

DEFAULT_DWELL = 20


def load_surface(screens_dir, name, overrides=None):
    """Load `<screens_dir>/<name>.json` with source overrides merged in and validate it, without starting sources."""
    overrides = overrides or {}
    with open(os.path.join(screens_dir, f"{name}.json")) as f:
        config = json.load(f)
    for spec in config.get("sources", []):
        if isinstance(spec, dict) and spec.get("mount") in overrides:
            spec.update(overrides[spec["mount"]])
    unknown = set(overrides) - {s.get("mount") for s in config.get("sources", []) if isinstance(s, dict)}
    if unknown:
        raise ConfigError(f"overrides for sources the screen doesn't have: {sorted(unknown)}")
    return Surface.load(config)


class App:
    def __init__(self, model, screens_dir="screens", live=False, clock=time.monotonic):
        self.model = model
        self.screens_dir = screens_dir
        self.live = live
        self._clock = clock
        self.active = None          # name of the running screen
        self._surface = None
        self._screen_dm = None
        self._static = None         # sample-data source for the running screen
        self._signature = None      # (name, overrides) the running screen was built from
        self._failed = None         # signature that last failed to load, so it logs once
        self._index = 0
        self._since = None

    # ---- what should be showing ----

    def desired(self):
        """Name of the screen the model asks for, or None when powered off or nothing is configured."""
        if self.model.get("/app/power", True) is False:
            return None
        pinned = self.model.get("/app/screen")
        if pinned:
            self._since = None      # restart the rotation when the pin is lifted
            return pinned
        rotation = self.model.get("/app/rotation") or {}
        names = rotation.get("screens") or []
        if not names:
            return self.active
        dwell = rotation.get("dwell", DEFAULT_DWELL)
        now = self._clock()
        if self._since is None or self._index >= len(names):
            self._index, self._since = 0, now
        elif now - self._since >= dwell:
            self._index, self._since = (self._index + 1) % len(names), now
        return names[self._index]

    def overrides(self, name):
        value = self.model.get(f"/app/screens/{name}/sources")
        return value if isinstance(value, dict) else {}

    def brightness(self):
        value = self.model.get("/app/brightness")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return max(1, min(100, int(value)))

    # ---- switching ----

    def update(self):
        """Reconcile the running screen with the model. Call once per frame."""
        name = self.desired()
        if name is None:
            self._stop()
            self.model.set("/status/active", None)
            return
        signature = (name, json.dumps(self.overrides(name), sort_keys=True))
        if signature == self._signature or signature == self._failed:
            return
        try:
            surface, screen_dm, static = self._build(name, self.overrides(name))
        except (OSError, ValueError) as e:       # ConfigError is a ValueError; keep the old screen up
            self._failed = signature
            self.model.set("/status/error", f"{name}: {e}")
            log.error("screen %r not loaded: %s", name, e)
            return
        self._stop()
        self._surface, self._screen_dm, self._static = surface, screen_dm, static
        self.active, self._signature, self._failed = name, signature, None
        self.model.set("/status/active", name)
        self.model.set("/status/error", None)

    def _build(self, name, overrides):
        surface = load_surface(self.screens_dir, name, overrides)
        dm, static = DataModel(), None
        if self.live:
            if not surface.sources:
                raise ConfigError("screen declares no \"sources\"")
            surface.start_sources(dm)
        else:
            sample = os.path.join(self.screens_dir, f"{name}.sample_data.json")
            if os.path.exists(sample):
                static = StaticFileSource(sample).start(dm)
        return surface, dm, static

    def _stop(self):
        if self._surface:
            self._surface.stop_sources()
        if self._static:
            self._static.stop()
        self._surface = self._screen_dm = self._static = None
        self.active = self._signature = None

    def stop(self):
        self._stop()

    # ---- drawing ----

    def render(self, canvas, fonts, graphics):
        if self._surface:
            self._surface.render(canvas, self._screen_dm, fonts, graphics)
