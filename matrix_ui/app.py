"""The global model: one DataModel that decides which screen runs and how it is configured.

Model layout (`/app` is the control state, loaded from a JSON file and reloaded when it changes):

  /app/power        false blanks the matrix (default true)
  /app/brightness   1-100
  /app/sleep        {"start": "23:00", "end": "07:00"}: local-time window with the matrix dark (brightness 0, no screen
                    running); the window may span midnight.
                    Or {"weekday": {...}, "weekend": {...}} with a window each (Sat/Sun are the weekend); a day with no
                    window doesn't sleep. The window is chosen by the current day, even after midnight
  /app/screen       pin this screen by name; wins over the rotation
  /app/schedule     a list of rules, first match wins (so put the rarest on top): [{"screen": "weather", "at":
                    "0 */15 * * * *", "for": 15}, ..., {"screen": "subway"}]. `at` is a cron expression (5 fields, or 6
                    with leading seconds, local time); the screen shows for `for` seconds (default 60) from each firing.
                    A rule without `at` always matches, so it is the fallback. Wins over the rotation
  /app/rotation     {"screens": ["subway", "weather"], "dwell": 20}   dwell is seconds per screen
  /app/screens/<name>/sources/<mount>   {param: value}, merged over that screen's source of that mount

`/status` is written by the App itself (`/status/active`, `/status/error`) and never by the file.
Each screen keeps its own DataModel for its data, so screens can't clobber each other's paths.
"""
import json
import logging
import os
import time

from .cron import Cron
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


def _minutes(hhmm):
    """Minutes since midnight for an "HH:MM" string."""
    hour, minute = str(hhmm).split(":")
    hour, minute = int(hour), int(minute)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(hhmm)
    return hour * 60 + minute


class App:
    def __init__(self, model, screens_dir="screens", live=False, clock=time.monotonic, wall=time.time):
        self.model = model
        self.screens_dir = screens_dir
        self.live = live
        self._clock = clock
        self._wall = wall
        self.active = None          # name of the running screen
        self._surface = None
        self._screen_dm = None
        self._static = None         # sample-data source for the running screen
        self._signature = None      # (name, overrides) the running screen was built from
        self._failed = None         # signature that last failed to load, so it logs once
        self._index = 0
        self._since = None
        self._crons = {}

    # ---- what should be showing ----

    def desired(self):
        """Name of the screen the model asks for, or None when powered off or nothing is configured."""
        if self.model.get("/app/power", True) is False or self.asleep():
            return None
        pinned = self.model.get("/app/screen")
        if pinned:
            self._since = None      # restart the rotation when the pin is lifted
            return pinned
        scheduled = self._scheduled()
        if scheduled:
            self._since = None
            return scheduled
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

    def _scheduled(self):
        """The first `/app/schedule` rule that matches right now, or None. Rules that don't parse are skipped."""
        rules = self.model.get("/app/schedule")
        if not isinstance(rules, list):
            return None
        now = self._wall()
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("screen"):
                continue
            if not rule.get("at"):
                return rule["screen"]
            length = rule.get("for", 60)
            if isinstance(length, bool) or not isinstance(length, (int, float)) or length <= 0:
                continue
            try:
                if self._cron(rule["at"]).active(now, length):
                    return rule["screen"]
            except (ValueError, TypeError):
                continue
        return None

    def _cron(self, expr):
        if expr not in self._crons:
            self._crons[expr] = Cron(expr)
        return self._crons[expr]

    def asleep(self):
        """True while the local time is inside the `/app/sleep` window; a missing or malformed window never sleeps."""
        window = self.model.get("/app/sleep")
        now = time.localtime(self._wall())
        if isinstance(window, dict) and ("weekday" in window or "weekend" in window):
            window = window.get("weekend" if now.tm_wday >= 5 else "weekday")
        if not isinstance(window, dict):
            return False
        try:
            start, end = (_minutes(window[k]) for k in ("start", "end"))
        except (KeyError, TypeError, ValueError):
            return False
        now = now.tm_hour * 60 + now.tm_min
        if start == end:
            return False
        return start <= now < end if start < end else now >= start or now < end

    def overrides(self, name):
        value = self.model.get(f"/app/screens/{name}/sources")
        return value if isinstance(value, dict) else {}

    def brightness(self):
        if self.asleep():
            return 0
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
