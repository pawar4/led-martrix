"""Data sources: background workers that write into a DataModel.

A source owns one subtree (`mount`) of the model and replaces it atomically, so a
render never sees a half-updated value. A failed fetch keeps the last good data.
"""
import json
import logging
import os
import re
import threading
import time
import urllib.request

from .resolver import ConfigError

log = logging.getLogger(__name__)


class Source:
    """Base class. Subclasses implement `_run`, which loops until `self._stop` is set."""

    def __init__(self, mount=""):
        self.mount = mount
        self.last_update = None      # time.time() of the last successful update
        self._dm = None
        self._stop = threading.Event()
        self._thread = None

    def start(self, dm):
        self._dm = dm
        self._thread = threading.Thread(target=self._run, name=type(self).__name__, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def age(self):
        """Seconds since the last successful update, or None if there hasn't been one."""
        return None if self.last_update is None else time.time() - self.last_update

    def publish(self, value):
        self._dm.set(self.mount, value)
        self.last_update = time.time()

    def _run(self):
        raise NotImplementedError


class StaticFileSource(Source):
    """Load a JSON file, and reload it whenever it changes on disk."""

    def __init__(self, path, mount="", interval=0.5):
        super().__init__(mount)
        self.path = path
        self.interval = interval

    def _run(self):
        mtime = None
        while not self._stop.is_set():
            try:
                m = os.path.getmtime(self.path)
                if m != mtime:
                    with open(self.path) as f:
                        self.publish(json.load(f))
                    mtime = m
            except (OSError, ValueError) as e:
                log.warning("%s: %s", self.path, e)
            self._stop.wait(self.interval)


class FetchCache:
    """Last fetched value per key, shared by every PollingSource, so a restarted source reuses fresh data."""

    def __init__(self):
        self._entries = {}
        self._lock = threading.Lock()

    def get(self, key):
        """(fetched_at, value), or None."""
        with self._lock:
            return self._entries.get(key)

    def put(self, key, value):
        with self._lock:
            self._entries[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._entries.clear()


FETCH_CACHE = FetchCache()


class PollingSource(Source):
    """Call `fetch()` every `interval` seconds and publish the result at `mount`.

    With a `key`, results are memoized in `cache`: a source (re)started within `interval` of the last fetch
    for that key publishes the cached value at once and only fetches when it goes stale. Switching screens
    therefore doesn't refetch. Stale data is still published first, so the screen is never blank.
    """

    def __init__(self, fetch, interval=30, mount="", key=None, cache=FETCH_CACHE):
        super().__init__(mount)
        self.fetch = fetch
        self.interval = interval
        self.key = key
        self.cache = cache

    def _run(self):
        while not self._stop.is_set():
            wait = self.interval
            hit = self.cache.get(self.key) if self.key is not None else None
            if hit:
                fetched_at, value = hit
                if self.last_update is None or self.last_update < fetched_at:
                    self.publish(value)
                    self.last_update = fetched_at
                wait = fetched_at + self.interval - time.time()
            if not hit or wait <= 0:
                wait = self.interval
                try:
                    value = self.fetch()
                    if self.key is not None:
                        self.cache.put(self.key, value)
                    self.publish(value)
                except Exception as e:      # keep the last good data on any failure
                    log.warning("%s fetch failed: %s", self.mount or "/", e)
            self._stop.wait(wait)


def http_json(url, headers=None, timeout=10):
    """A `fetch` callable for PollingSource that GETs a URL and parses the JSON body."""
    def fetch():
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    return fetch


# ---- config-driven construction ----
#
# A screen config may carry a top-level "sources" list:
#   {"type": "http_json", "mount": "/weather", "url": "https://...", "interval": 60}
# Each source type declares its params as {name: (validator, default)}; a default of REQUIRED means the
# config must supply it. "mount" is accepted by every type.

REQUIRED = object()
SOURCE_TYPES = {}


def source_type(name, **params):
    """Register `factory(mount, **params) -> Source` under `name`."""
    def deco(factory):
        SOURCE_TYPES[name] = (params, factory)
        return factory
    return deco


def v_mount(v):
    if not isinstance(v, str) or not v.startswith("/"):
        raise ValueError(f"expected a path starting with '/', got {v!r}")
    return v


def v_str(v):
    if not isinstance(v, str) or not v:
        raise ValueError(f"expected a non-empty string, got {v!r}")
    return v


def v_number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"expected a number, got {v!r}")
    return v


def v_interval(v):
    if v_number(v) <= 0:
        raise ValueError(f"expected a positive number of seconds, got {v!r}")
    return v


def v_headers(v):
    if not isinstance(v, dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()):
        raise ValueError(f"expected an object of string headers, got {v!r}")
    return v


def expand_env(text):
    """Replace ${NAME} with the environment variable, so secrets stay out of screen files."""
    def sub(m):
        if m.group(1) not in os.environ:
            raise ConfigError(f"environment variable {m.group(1)} is not set")
        return os.environ[m.group(1)]
    return re.sub(r"\$\{(\w+)\}", sub, text)


def build_source(spec):
    where = f"source {spec.get('type')!r}" if isinstance(spec, dict) else "source"
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: expected an object, got {spec!r}")
    if spec.get("type") not in SOURCE_TYPES:
        raise ConfigError(f"{where}: unknown type, expected one of {sorted(SOURCE_TYPES)}")
    params, factory = SOURCE_TYPES[spec["type"]]
    allowed = {"type", "mount", *params}
    extra = set(spec) - allowed
    if extra:
        raise ConfigError(f"{where}: unknown keys {sorted(extra)}, allowed {sorted(allowed - {'type'})}")
    try:
        if "mount" not in spec:
            raise ValueError("'mount' is required")
        values = {}
        for name, (validator, default) in params.items():
            if name in spec:
                values[name] = validator(spec[name])
            elif default is REQUIRED:
                raise ValueError(f"'{name}' is required")
            else:
                values[name] = default
        source = factory(v_mount(spec["mount"]), **values)
        if isinstance(source, PollingSource):     # same type + params (any mount, any interval) share cached data
            key = {k: v for k, v in values.items() if k != "interval"}
            source.key = (spec["type"], json.dumps(key, sort_keys=True, default=str))
        return source
    except ValueError as e:      # ConfigError is a ValueError too
        raise ConfigError(f"{where}: {e}") from None


def build_sources(specs):
    if not isinstance(specs, list):
        raise ConfigError("'sources' must be a list")
    sources = [build_source(s) for s in specs]
    mounts = [s.mount for s in sources]
    for m in mounts:
        if any(o != m and (o.startswith(m + "/") or m.startswith(o + "/")) for o in mounts) or mounts.count(m) > 1:
            raise ConfigError(f"sources overlap at mount '{m}'; each source needs its own subtree")
    return sources


@source_type("file", path=(v_str, REQUIRED), interval=(v_interval, 0.5))
def _file(mount, path, interval):
    return StaticFileSource(path, mount, interval)


@source_type("http_json", url=(v_str, REQUIRED), headers=(v_headers, None), interval=(v_interval, 30))
def _http_json(mount, url, headers, interval):
    url = expand_env(url)
    headers = {k: expand_env(v) for k, v in (headers or {}).items()}
    return PollingSource(http_json(url, headers), interval, mount)
