import logging
from pathlib import Path

from src.gtfs.models.LineData import LineData
from src.output.LinesWriter import LinesWriter

logger = logging.getLogger(__name__)

# Fixed-point scale for stored coordinates: 1e6 ≈ 0.11 m at the equator.
COORD_SCALE = 1_000_000


class LinesSerializer:
    """Serialization for lines.bin.

    Line geometry is period-independent, so lines.bin is written once at the
    output root (a sibling of any per-period folders), not inside each period.
    """

    @staticmethod
    def write_lines_file(
        output_path: Path, lines: list[LineData], schema_version: int
    ) -> str:
        """Write lines.bin and return its path."""
        output_path.mkdir(parents=True, exist_ok=True)
        lines_path = output_path / "lines.bin"

        total_points = 0
        with open(lines_path, "wb") as f:
            writer = LinesWriter(f)
            writer.write_header(schema_version, COORD_SCALE, len(lines))
            for line in lines:
                writer.write_line(line, COORD_SCALE)
                total_points += sum(len(path.points) for path in line.paths)

        logger.info(f"Wrote {lines_path} ({len(lines)} lines, {total_points} points)")
        return str(lines_path)
