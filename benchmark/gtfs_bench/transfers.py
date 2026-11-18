"""Walking transfers between nearby stops, in the shape the pipeline reads them.

The pipeline can generate these itself (--gen-transfers), but by comparing every stop
with every other one: fine for a city, out of reach for France. Here a KD-tree finds, for
each stop, its neighbours within `radius_m`, capped at the `max_neighbors` closest.

The pipeline reads transfers.txt one way (from_stop_id -> to_stop_id) and treats an empty
min_transfer_time as 0, so every pair is written both ways with an explicit time:
distance / walking speed, never under `floor_s`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .geo import project


@dataclass(frozen=True)
class TransferParams:
    radius_m: float = 300.0
    max_neighbors: int = 30
    walk_speed_mps: float = 1.33   # the pipeline's own default (--speed-walk)
    floor_s: int = 60


def walking_transfers(stops: pd.DataFrame, params: TransferParams = TransferParams()) -> pd.DataFrame:
    """Columns from_stop_id, to_stop_id, min_transfer_time; both directions of every pair."""
    columns = ["from_stop_id", "to_stop_id", "min_transfer_time"]
    if len(stops) < 2:
        return pd.DataFrame(columns=columns)
    xy = project(stops["lat"].to_numpy(), stops["lon"].to_numpy())
    k = min(params.max_neighbors + 1, len(stops))  # +1: the nearest point is the stop itself
    distances, neighbours = cKDTree(xy).query(xy, k=k, distance_upper_bound=params.radius_m)
    distances, neighbours = np.atleast_2d(distances), np.atleast_2d(neighbours)
    origin = np.repeat(np.arange(len(stops)), k).reshape(len(stops), k)
    valid = np.isfinite(distances) & (neighbours != origin)
    a, b, d = origin[valid], neighbours[valid], distances[valid]
    # A cap on neighbours is not symmetric (B may be among A's 30 closest but not the other
    # way round): keep the pair both ways, at its shortest time.
    a, b, d = np.concatenate([a, b]), np.concatenate([b, a]), np.concatenate([d, d])
    seconds = np.maximum(params.floor_s, np.ceil(d / params.walk_speed_mps)).astype(np.int64)
    ids = stops["stop_id"].to_numpy()
    frame = pd.DataFrame({"from_stop_id": ids[a], "to_stop_id": ids[b], "min_transfer_time": seconds})
    return frame.groupby(["from_stop_id", "to_stop_id"], as_index=False, sort=False)["min_transfer_time"].min()
