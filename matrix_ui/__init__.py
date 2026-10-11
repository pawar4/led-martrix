"""Config-driven widget layer over the RGB LED matrix."""
from . import providers  # noqa: F401  (registers the weather / mta_arrivals source types)
from .datamodel import DataModel
from .resolver import ConfigError, Surface
from .sources import PollingSource, Source, StaticFileSource, http_json

__all__ = ["ConfigError", "DataModel", "PollingSource", "Source", "StaticFileSource", "Surface", "http_json"]
