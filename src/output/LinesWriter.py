from src.gtfs.models.LineData import LineData
from src.output.BinaryWriter import BinaryWriter
from src.transform.TimeCompressor import TimeCompressor


class LinesWriter(BinaryWriter):
    """Writer for lines.bin (v2) — transit line geometry from GTFS shapes.

    Coordinates are stored as fixed-point integers (``round(coord * coord_scale)``)
    and delta-encoded per axis, mirroring the delta encoding used for stop times
    in routes.bin. This keeps the over-sampled shape geometry compact.
    """

    MAGIC = b"RLN2"

    def write_header(self, schema_version: int, coord_scale: int, line_count: int) -> None:
        """Write lines.bin header."""
        self.write_bytes(self.MAGIC)
        self.write_uint16(schema_version)
        self.write_uint32(coord_scale)
        self.write_uint32(line_count)

    def write_line(self, line: LineData, coord_scale: int) -> int:
        """Write a single line and return its offset (v2 layout)."""
        line_offset = self.offset

        self.write_uint32(line.line_id_internal)
        self.write_string(line.name)
        self.write_string(line.color)
        self.write_string(line.text_color)
        self.write_uint16(line.transport_type)
        self.write_uint16(len(line.paths))

        for path in line.paths:
            self.write_uint16(path.direction_id)
            self.write_uint32(len(path.points))

            xs = [round(lon * coord_scale) for lon, _ in path.points]
            ys = [round(lat * coord_scale) for _, lat in path.points]

            # Columnar, delta-encoded: all X then all Y (first value absolute).
            for value in TimeCompressor.encode_times(xs):
                self.write_int32(value)
            for value in TimeCompressor.encode_times(ys):
                self.write_int32(value)

        return line_offset
