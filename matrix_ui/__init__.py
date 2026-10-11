"""Config-driven widget layer over the RGB LED matrix."""
from .datamodel import DataModel
from .resolver import ConfigError, Surface

__all__ = ["ConfigError", "DataModel", "Surface"]
