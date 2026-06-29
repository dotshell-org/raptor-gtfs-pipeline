import logging
import math

import numpy as np

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.StopData import StopData

logger = logging.getLogger(__name__)


class TransferBuilder:
    """Transfer calculation and generation."""

    @staticmethod
    def build_transfers(
        reader: GTFSReader,
        stops: list[StopData],
        gen_transfers: bool = False,
        speed_walk: float = 1.33,
        transfer_cutoff: int = 500,
    ) -> None:
        """Build transfer data for stops."""
        logger.info("Building transfers")

        gtfs_to_internal = {stop.stop_id_gtfs: stop.stop_id_internal for stop in stops}

        if hasattr(reader, "transfers_df"):
            df = reader.transfers_df
            # Join with internal IDs
            df = df.copy()
            df["from_int"] = df["from_stop_id"].map(gtfs_to_internal)
            df["to_int"] = df["to_stop_id"].map(gtfs_to_internal)

            # Drop transfers to unknown stops
            valid = df.dropna(subset=["from_int", "to_int"])
            if len(valid) < len(df):
                logger.warning(f"Dropped {len(df) - len(valid)} transfers referencing unknown stops")

            for _, row in valid.iterrows():
                from_id = int(row["from_int"])
                to_id = int(row["to_int"])
                stops[from_id].transfers.append((to_id, int(row["_min_time"])))

        if gen_transfers:
            logger.info(
                f"Generating transfers with cutoff {transfer_cutoff}m "
                f"and walk speed {speed_walk}m/s"
            )
            TransferBuilder._generate_walking_transfers(stops, speed_walk, transfer_cutoff)

        # Sort and deduplicate transfers (keep minimum time per target)
        for stop in stops:
            if stop.transfers:
                transfer_map: dict[int, int] = {}
                for target_id, walk_time in stop.transfers:
                    if target_id not in transfer_map:
                        transfer_map[target_id] = walk_time
                    else:
                        transfer_map[target_id] = min(transfer_map[target_id], walk_time)
                stop.transfers = sorted(transfer_map.items())

        total_transfers = sum(len(stop.transfers) for stop in stops)
        logger.info(f"Built {total_transfers} transfers")

    @staticmethod
    def _generate_walking_transfers(
        stops: list[StopData], speed_walk: float, cutoff: int
    ) -> None:
        """Generate walking transfers using vectorized numpy broadcasting (O(n²) → C speed)."""
        n = len(stops)
        if n == 0:
            return

        # Optimization: use chunks to avoid huge memory allocation for O(n^2) distance matrix
        chunk_size = 2000 
        
        lats_all = np.radians(np.array([s.lat for s in stops], dtype=np.float32))
        lons_all = np.radians(np.array([s.lon for s in stops], dtype=np.float32))
        internal_ids = np.array([s.stop_id_internal for s in stops], dtype=np.int32)

        for i in range(0, n, chunk_size):
            end_i = min(i + chunk_size, n)
            lats_i = lats_all[i:end_i, None]
            lons_i = lons_all[i:end_i, None]
            
            # Distance calculation for chunk i against all stops j > i
            # To keep it memory efficient, we can further chunk the second dimension or just process j > i
            for j in range(i, n, chunk_size):
                end_j = min(j + chunk_size, n)
                
                lats_j = lats_all[None, j:end_j]
                lons_j = lons_all[None, j:end_j]
                
                dlat = lats_i - lats_j
                dlon = lons_i - lons_j
                
                a = (
                    np.sin(dlat / 2) ** 2
                    + np.cos(lats_i) * np.cos(lats_j) * np.sin(dlon / 2) ** 2
                )
                # Use float32 to save memory
                distances = (6371000.0 * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))).astype(np.float32)
                
                # Filter by cutoff and i < j (to avoid diagonal and double counting)
                mask = distances <= cutoff
                if i == j:
                    # Exclude lower triangle and diagonal in the square block
                    mask &= np.triu(np.ones(mask.shape, dtype=bool), k=1)
                
                rows, cols = np.where(mask)
                
                for r, c in zip(rows.tolist(), cols.tolist()):
                    idx_i = i + r
                    idx_j = j + c
                    walk_time = int(distances[r, c] / speed_walk)
                    stops[idx_i].transfers.append((internal_ids[idx_j], walk_time))
                    stops[idx_j].transfers.append((internal_ids[idx_i], walk_time))

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Scalar haversine distance between two points in meters (kept for reference)."""
        r = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
