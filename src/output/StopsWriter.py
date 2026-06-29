from src.gtfs.models.StopData import StopData
from src.output.BinaryWriter import BinaryWriter


class StopsWriter(BinaryWriter):
    """Writer for stops.bin."""

    MAGIC = b"RST2"

    def write_header(self, schema_version: int, stop_count: int) -> None:
        """Write stops.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)
        self.write_uint32(stop_count)

    def write_stop(self, stop: StopData) -> int:
        """Write a single stop and return its offset."""
        stop_offset = self.offset

        self.write_uint32(stop.stop_id_internal)
        self.write_string(stop.name)
        self.write_float64(stop.lat)
        self.write_float64(stop.lon)

        # Write route references
        self.write_uint32(len(stop.route_ids))
        for route_id in stop.route_ids:
            self.write_uint32(route_id)

        # Write transfers
        self.write_uint32(len(stop.transfers))
        for target_stop, walk_time in stop.transfers:
            self.write_uint32(target_stop)
            self.write_int32(walk_time)

        return stop_offset
