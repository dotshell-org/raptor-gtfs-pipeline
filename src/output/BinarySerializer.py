import logging
from pathlib import Path

from src.output.RoutesWriter import RoutesWriter
from src.output.StopsWriter import StopsWriter
from src.output.IndexWriter import IndexWriter
from src.gtfs.models.RouteData import RouteData
from src.gtfs.models.StopData import StopData
from src.gtfs.models.NetworkIndex import NetworkIndex

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
    ) -> dict[str, str]:
        """Write all binary files and return filenames."""
        logger.info(f"Writing binary files to {output_path}")

        output_path.mkdir(parents=True, exist_ok=True)

        files_written = {}

        # Write routes.bin
        routes_path = output_path / "routes.bin"
        with open(routes_path, "wb") as f:
            writer = RoutesWriter(f)
            writer.write_header(schema_version, len(routes))

            for route in routes:
                offset = writer.write_route(route, compression=compression)
                index.route_offsets[route.route_id_internal] = offset

        files_written["routes.bin"] = str(routes_path)
        logger.info(f"Wrote {routes_path}")

        # Write stops.bin
        stops_path = output_path / "stops.bin"
        with open(stops_path, "wb") as f:
            stops_writer = StopsWriter(f)
            stops_writer.write_header(schema_version, len(stops))

            for stop in stops:
                offset = stops_writer.write_stop(stop)
                index.stop_offsets[stop.stop_id_internal] = offset

        files_written["stops.bin"] = str(stops_path)
        logger.info(f"Wrote {stops_path}")

        # Write index.bin
        index_path = output_path / "index.bin"
        with open(index_path, "wb") as f:
            index_writer = IndexWriter(f)
            index_writer.write_header(schema_version)
            index_writer.write_index(index)

        files_written["index.bin"] = str(index_path)
        logger.info(f"Wrote {index_path}")

        return files_written
