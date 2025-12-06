"""JSON debug output."""

import json
import logging
from pathlib import Path

from raptor_pipeline.gtfs.models import NetworkIndex, RouteData, StopData

logger = logging.getLogger(__name__)


def write_json_files(
    output_path: Path,
    routes: list[RouteData],
    stops: list[StopData],
    index: NetworkIndex,
) -> dict[str, str]:
    """Write debug JSON files."""
    logger.info(f"Writing debug JSON files to {output_path}")

    output_path.mkdir(parents=True, exist_ok=True)

    files_written = {}

    # Write routes.json
    routes_data = []
    for route in routes:
        trips_data = []
        for trip in route.trips:
            trips_data.append(
                {
                    "trip_id_internal": trip.trip_id_internal,
                    "trip_id_gtfs": trip.trip_id_gtfs,
                    "arrival_times": trip.arrival_times,
                    "is_partial": trip.is_partial,
                }
            )

        routes_data.append(
            {
                "route_id_internal": route.route_id_internal,
                "route_id_gtfs": route.route_id_gtfs,
                "stop_ids": route.stop_ids,
                "trip_count": len(route.trips),
                "trips": trips_data,
            }
        )

    routes_path = output_path / "routes.json"
    with open(routes_path, "w", encoding="utf-8") as f:
        json.dump(routes_data, f, indent=2, sort_keys=True)
    files_written["routes.json"] = str(routes_path)
    logger.info(f"Wrote {routes_path}")

    # Write stops.json
    stops_data = []
    for stop in stops:
        stops_data.append(
            {
                "stop_id_internal": stop.stop_id_internal,
                "stop_id_gtfs": stop.stop_id_gtfs,
                "name": stop.name,
                "lat": stop.lat,
                "lon": stop.lon,
                "route_ids": stop.route_ids,
                "transfers": [
                    {"target_stop_id": target, "walk_time": time} for target, time in stop.transfers
                ],
            }
        )

    stops_path = output_path / "stops.json"
    with open(stops_path, "w", encoding="utf-8") as f:
        json.dump(stops_data, f, indent=2, sort_keys=True)
    files_written["stops.json"] = str(stops_path)
    logger.info(f"Wrote {stops_path}")

    # Write index.json
    index_data = {
        "stop_to_routes": {
            str(stop_id): routes for stop_id, routes in index.stop_to_routes.items()
        },
        "route_offsets": {
            str(route_id): offset for route_id, offset in index.route_offsets.items()
        },
        "stop_offsets": {str(stop_id): offset for stop_id, offset in index.stop_offsets.items()},
    }

    index_path = output_path / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, sort_keys=True)
    files_written["index.json"] = str(index_path)
    logger.info(f"Wrote {index_path}")

    return files_written
