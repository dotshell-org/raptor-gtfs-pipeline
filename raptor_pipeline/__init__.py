"""Raptor GTFS Pipeline - Convert GTFS datasets to compact binary formats."""

from raptor_pipeline.api import convert, validate
from raptor_pipeline.version import SCHEMA_VERSION, VERSION

__version__ = VERSION
__all__ = ["SCHEMA_VERSION", "VERSION", "convert", "validate"]
