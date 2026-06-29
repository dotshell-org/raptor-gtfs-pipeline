from src.output.BinaryWriter import BinaryWriter
from src.gtfs.models.NetworkIndex import NetworkIndex


class IndexWriter(BinaryWriter):
    """Writer for index.bin."""

    MAGIC = b"RIDX"

    def write_header(self, schema_version: int) -> None:
        """Write index.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)

    def write_index(self, index: NetworkIndex) -> None:
        """Write complete index data."""
        # Write stop_to_routes
        self.write_uint32(len(index.stop_to_routes))
        for stop_id in sorted(index.stop_to_routes.keys()):
            route_ids = index.stop_to_routes[stop_id]
            self.write_uint32(stop_id)
            self.write_uint32(len(route_ids))
            for route_id in route_ids:
                self.write_uint32(route_id)

        # Write route_offsets
        self.write_uint32(len(index.route_offsets))
        for route_id in sorted(index.route_offsets.keys()):
            offset = index.route_offsets[route_id]
            self.write_uint32(route_id)
            self.write_uint64(offset)

        # Write stop_offsets
        self.write_uint32(len(index.stop_offsets))
        for stop_id in sorted(index.stop_offsets.keys()):
            offset = index.stop_offsets[stop_id]
            self.write_uint32(stop_id)
            self.write_uint64(offset)
