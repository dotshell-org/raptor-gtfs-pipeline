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


@dataclass(frozen=True)
class StationParams:
    """Wider links around the stations of national networks (rail, coach, ferry).

    A long-distance train stops at a station whose platforms can lie further from the city's
    metro, tram and bus stops than a plain walking transfer reaches (Paris Montparnasse,
    Gare de Lyon and Bercy, Lille Flandres and Europe), and at a big hub the 30 closest stops
    may all be bus poles. From a station's stops, links reach `radius_m`, up to the
    `max_neighbors` closest.

    SNCF stop ids carry the station's UIC code ("StopPoint:OCETGV INOUI-87686006"): stops
    sharing a code are one station whatever their coordinates say, up to `uic_max_m` apart
    (beyond that, a coordinate is wrong and the link would teleport).
    """
    radius_m: float = 500.0
    max_neighbors: int = 60
    uic_pattern: str = r"OCE[^-]*-(\d{8})$"
    uic_max_m: float = 2000.0


def station_transfers(stops: pd.DataFrame, is_station: np.ndarray, params: StationParams = StationParams(),
                      walking: TransferParams = TransferParams()) -> pd.DataFrame:
    """Links from station stops (`is_station`) to every stop nearby, and between stops of one UIC code.

    Same columns and conventions as walking_transfers: both directions, walking time.
    """
    columns = ["from_stop_id", "to_stop_id", "min_transfer_time"]
    stations = np.flatnonzero(np.asarray(is_station, dtype=bool))
    if len(stops) < 2 or not len(stations):
        return pd.DataFrame(columns=columns)
    xy = project(stops["lat"].to_numpy(), stops["lon"].to_numpy())
    k = min(params.max_neighbors + 1, len(stops))
    distances, neighbours = cKDTree(xy).query(xy[stations], k=k, distance_upper_bound=params.radius_m)
    distances, neighbours = np.atleast_2d(distances), np.atleast_2d(neighbours)
    origin = np.repeat(stations, k).reshape(len(stations), k)
    valid = np.isfinite(distances) & (neighbours != origin)
    a, b = [origin[valid]], [neighbours[valid]]

    codes = stops["stop_id"].iloc[stations].str.extract(params.uic_pattern, expand=False)
    by_code = pd.DataFrame({"index": stations, "code": codes.to_numpy()}).dropna()
    pairs = by_code.merge(by_code, on="code")
    pairs = pairs[pairs["index_x"] != pairs["index_y"]]
    a.append(pairs["index_x"].to_numpy())
    b.append(pairs["index_y"].to_numpy())

    a, b = np.concatenate(a), np.concatenate(b)
    d = np.hypot(*(xy[a] - xy[b]).T)
    keep = d <= max(params.radius_m, params.uic_max_m)
    a, b, d = a[keep], b[keep], d[keep]
    a, b, d = np.concatenate([a, b]), np.concatenate([b, a]), np.concatenate([d, d])
    seconds = np.maximum(walking.floor_s, np.ceil(d / walking.walk_speed_mps)).astype(np.int64)
    ids = stops["stop_id"].to_numpy()
    frame = pd.DataFrame({"from_stop_id": ids[a], "to_stop_id": ids[b], "min_transfer_time": seconds})
    return frame.groupby(["from_stop_id", "to_stop_id"], as_index=False, sort=False)["min_transfer_time"].min()
