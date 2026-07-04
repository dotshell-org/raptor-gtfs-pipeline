import logging
from pathlib import Path

from src.gtfs.models.NetworkIndex import NetworkIndex
from src.gtfs.models.RouteData import RouteData
from src.gtfs.models.StopData import StopData
from src.output.IndexWriter import IndexWriter
from src.output.RoutesWriter import RoutesWriter
from src.output.StopsWriter import StopsWriter

logger = logging.getLogger(__name__)


class BinarySerializer:
    """Serialization logic for RAPTOR binary format."""

    @staticmethod
    def write_binary_files(
        output_path: Path,
        routes: list[RouteData],
        stops: list[StopData],
        index: NetworkIndex,
        schema_version: int,
        compression: bool = True,
        suffix: str = "",
        write_index: bool = True,
    ) -> dict[str, str]:
        """Write all binary files and return filenames.

        ``suffix`` is appended before the extension (e.g. ``_saturday``) for the
        flat, per-period app layout: ``routes_saturday.bin`` instead of nesting.
        ``write_index`` controls whether index.bin is emitted.
        """
        logger.debug(f"Writing binary files to {output_path}")

        output_path.mkdir(parents=True, exist_ok=True)

        files_written = {}

        # Write routes.bin
        routes_name = f"routes{suffix}.bin"
        routes_path = output_path / routes_name
        with open(routes_path, "wb") as f:
            writer = RoutesWriter(f)
            writer.write_header(schema_version, len(routes))

            for route in routes:
                offset = writer.write_route(route, compression=compression)
                index.route_offsets[route.route_id_internal] = offset

        files_written[routes_name] = str(routes_path)
        logger.debug(f"Wrote {routes_path}")

        # Write stops.bin
        stops_name = f"stops{suffix}.bin"
        stops_path = output_path / stops_name
        with open(stops_path, "wb") as f:
            stops_writer = StopsWriter(f)
            stops_writer.write_header(schema_version, len(stops))

            for stop in stops:
                offset = stops_writer.write_stop(stop)
                index.stop_offsets[stop.stop_id_internal] = offset

        files_written[stops_name] = str(stops_path)
        logger.debug(f"Wrote {stops_path}")

        # Write index.bin (optional)
        if write_index:
            index_name = f"index{suffix}.bin"
            index_path = output_path / index_name
            with open(index_path, "wb") as f:
                index_writer = IndexWriter(f)
                index_writer.write_header(schema_version)
                index_writer.write_index(index)

            files_written[index_name] = str(index_path)
            logger.debug(f"Wrote {index_path}")

        return files_written
