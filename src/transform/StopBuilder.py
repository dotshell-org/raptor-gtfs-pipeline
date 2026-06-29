import logging

from src.gtfs.models.RouteData import RouteData
from src.gtfs.models.StopData import StopData
from src.gtfs.GTFSReader import GTFSReader

logger = logging.getLogger(__name__)


class StopBuilder:
    """Stop indexation and metadata."""

    @staticmethod
    def build_stops(reader: GTFSReader, routes: list[RouteData]) -> list[StopData]:
        """Build StopData with route references."""
        logger.info("Building stop data with route references")

        # Create mapping from stop to routes
        stop_to_routes: dict[int, set[int]] = {}

        for route in routes:
            route_id = route.route_id_internal
            for stop_id in route.stop_ids:
                if stop_id not in stop_to_routes:
                    stop_to_routes[stop_id] = set()
                stop_to_routes[stop_id].add(route_id)

        # Build StopData
        stops: list[StopData] = []

        for stop in reader.stops:
            stop_id_internal = reader.get_internal_stop_id(stop.stop_id)

            route_ids = sorted(stop_to_routes.get(stop_id_internal, set()))

            stop_data = StopData(
                stop_id_internal=stop_id_internal,
                stop_id_gtfs=stop.stop_id,
                name=stop.name,
                lat=stop.lat,
                lon=stop.lon,
                route_ids=route_ids,
                transfers=[],  # Filled by transfers module
            )
            stops.append(stop_data)

        logger.info(f"Built {len(stops)} stops")
        return stops
