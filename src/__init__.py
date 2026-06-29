"""Raptor GTFS Pipeline - Convert GTFS datasets to compact binary formats."""

from src.PipelineConverter import PipelineConverter
from src.Version import Version

__version__ = Version.VERSION
__all__ = ["Version", "PipelineConverter"]
