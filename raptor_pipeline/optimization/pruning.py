"""Pruning and optimization metadata (stub for future enhancements)."""

import logging

from raptor_pipeline.gtfs.models import RouteData

logger = logging.getLogger(__name__)


def compute_pruning_metadata(routes: list[RouteData]) -> dict[str, int]:
    """
    Compute pruning metadata for routes.

    Stub for future optimizations like:
    - Earliest/latest trip times per route
    - Route dominance relationships
    - Stop reachability windows
    """
    logger.info("Computing pruning metadata (stub)")

    # Basic statistics for now
    metadata = {
        "total_routes": len(routes),
        "total_trips": sum(len(route.trips) for route in routes),
        "total_stops": sum(len(route.stop_ids) for route in routes),
    }

    return metadata
