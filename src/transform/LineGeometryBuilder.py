import logging
from collections import defaultdict

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.LineData import LineData, LinePath

logger = logging.getLogger(__name__)


class LineGeometryBuilder:
    """Build per-line geometry from GTFS ``shapes.txt``.

    For every route, its trips are grouped by ``direction_id`` and the longest
    shape (most points) of each direction is kept as that direction's polyline.
    This is the same heuristic used for the standalone GeoJSON generator.
    """

    @staticmethod
    def build_lines(reader: GTFSReader) -> list[LineData]:
        """Return one :class:`LineData` per route that has usable shape geometry."""
        if not reader.shapes_points:
            logger.warning("No shapes loaded — cannot build line geometry")
            return []
        if reader.trips_df.empty or "shape_id" not in reader.trips_df.columns:
            logger.warning("No trips/shape_id available — cannot build line geometry")
            return []

        # route_id -> {direction_id -> [shape_id, ...]} (order-preserving, deduped)
        grouped = (
            reader.trips_df.groupby(["route_id", "direction_id"])["shape_id"]
            .apply(lambda s: [sid for sid in dict.fromkeys(s) if sid])
        )
        shapes_by_route: dict[str, dict[int, list[str]]] = defaultdict(dict)
        for key, shape_ids in grouped.items():
            route_id, direction_id = key  # type: ignore[misc]
            shapes_by_route[str(route_id)][int(direction_id)] = list(shape_ids)

        lines: list[LineData] = []
        for route in reader.routes:
            per_direction = shapes_by_route.get(route.route_id)
            if not per_direction:
                continue

            paths: list[LinePath] = []
            for direction_id, shape_ids in sorted(per_direction.items()):
                best_points: list[tuple[float, float]] | None = None
                for shape_id in shape_ids:
                    points = reader.shapes_points.get(shape_id)
                    if points and (best_points is None or len(points) > len(best_points)):
                        best_points = points
                if best_points:
                    paths.append(LinePath(direction_id=direction_id, points=best_points))

            if not paths:
                continue

            name = route.route_short_name or route.route_long_name or route.route_id
            lines.append(
                LineData(
                    line_id_internal=reader.route_id_map[route.route_id],
                    name=name,
                    transport_type=route.route_type,
                    color=route.route_color,
                    text_color=route.route_text_color,
                    paths=paths,
                )
            )

        logger.info(f"Built geometry for {len(lines)} lines")
        return lines
