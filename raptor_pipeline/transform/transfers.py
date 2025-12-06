"""Transfer calculation and generation."""

import logging
import math

from raptor_pipeline.gtfs.models import StopData
from raptor_pipeline.gtfs.reader import GTFSReader

logger = logging.getLogger(__name__)


def build_transfers(
    reader: GTFSReader,
    stops: list[StopData],
    gen_transfers: bool = False,
    speed_walk: float = 1.33,
    transfer_cutoff: int = 500,
) -> None:
    """Build transfer data for stops."""
    logger.info("Building transfers")

    # Create mapping from GTFS stop ID to internal stop ID
    gtfs_to_internal = {stop.stop_id_gtfs: stop.stop_id_internal for stop in stops}

    # Process explicit transfers from GTFS
    for transfer in reader.transfers:
        from_stop_id = gtfs_to_internal.get(transfer.from_stop_id)
        to_stop_id = gtfs_to_internal.get(transfer.to_stop_id)

        if from_stop_id is None or to_stop_id is None:
            logger.warning(
                f"Transfer references unknown stops: "
                f"{transfer.from_stop_id} -> {transfer.to_stop_id}"
            )
            continue

        from_stop = stops[from_stop_id]
        from_stop.transfers.append((to_stop_id, transfer.min_transfer_time))

    # Generate implicit transfers if requested
    if gen_transfers:
        logger.info(
            f"Generating transfers with cutoff {transfer_cutoff}m and walk speed {speed_walk}m/s"
        )
        _generate_walking_transfers(stops, speed_walk, transfer_cutoff)

    # Sort and deduplicate transfers
    for stop in stops:
        if stop.transfers:
            # Deduplicate: keep minimum time for each target
            transfer_map: dict[int, int] = {}
            for target_id, walk_time in stop.transfers:
                if target_id not in transfer_map:
                    transfer_map[target_id] = walk_time
                else:
                    transfer_map[target_id] = min(transfer_map[target_id], walk_time)

            stop.transfers = sorted(transfer_map.items())

    total_transfers = sum(len(stop.transfers) for stop in stops)
    logger.info(f"Built {total_transfers} transfers")


def _generate_walking_transfers(stops: list[StopData], speed_walk: float, cutoff: int) -> None:
    """Generate walking transfers between nearby stops."""
    for i, stop_a in enumerate(stops):
        for stop_b in stops[i + 1 :]:
            distance = _haversine_distance(stop_a.lat, stop_a.lon, stop_b.lat, stop_b.lon)

            if distance <= cutoff:
                walk_time = int(distance / speed_walk)

                # Add bidirectional transfers
                stop_a.transfers.append((stop_b.stop_id_internal, walk_time))
                stop_b.transfers.append((stop_a.stop_id_internal, walk_time))


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate haversine distance between two points in meters."""
    R = 6371000  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
