from src.gtfs.models.RouteData import RouteData
from src.output.BinaryWriter import BinaryWriter
from src.transform.TimeCompressor import TimeCompressor


class RoutesWriter(BinaryWriter):
    """Writer for routes.bin."""

    MAGIC = b"RRT2"

    def write_header(self, schema_version: int, route_count: int) -> None:
        """Write routes.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)
        self.write_uint32(route_count)

    def write_route(self, route: RouteData, compression: bool = True) -> int:
        """Write a single route and return its offset (v2 layout)."""
        route_offset = self.offset

        self.write_uint32(route.route_id_internal)
        self.write_string(route.route_name)
        self.write_uint32(len(route.stop_ids))
        self.write_uint32(len(route.trips))

        # Write stop IDs
        for stop_id in route.stop_ids:
            self.write_uint32(stop_id)

        # Write all trip IDs as a block
        for trip in route.trips:
            self.write_uint32(trip.trip_id_internal)

        # Write all stop times as a flat block (row-major, pre-sorted)
        for trip in route.trips:
            times = [int(t) for t in trip.arrival_times if t != float("inf")]
            if compression:
                encoded_times = TimeCompressor.encode_times(times)
            else:
                encoded_times = times

            for time in encoded_times:
                self.write_int32(time)

        return route_offset
