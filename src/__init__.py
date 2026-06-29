"""Raptor GTFS Pipeline - Convert GTFS datasets to compact binary formats."""

from .api import convert
from .version import SCHEMA_VERSION, VERSION

__version__ = VERSION
__all__ = ["SCHEMA_VERSION", "VERSION", "convert"]
