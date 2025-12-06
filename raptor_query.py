#!/usr/bin/env python3
"""
RAPTOR algorithm implementation for journey planning.
Query: Stop #1307 → Stop #7588
"""

from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
import json
import struct
import csv


class BinaryReader:
    """Binary file reader."""

    def __init__(self, file):
        self.file = file

    def read_bytes(self, n: int) -> bytes:
        data = self.file.read(n)
        if len(data) != n:
            raise ValueError(f"Expected {n} bytes, got {len(data)}")
        return data

    def read_uint16(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_uint32(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def read_int32(self) -> int:
        return struct.unpack("<i", self.read_bytes(4))[0]

    def read_float64(self) -> float:
        return struct.unpack("<d", self.read_bytes(8))[0]

    def read_string(self) -> str:
        length = self.read_uint16()
        return self.read_bytes(length).decode("utf-8")


@dataclass
class Stop:
    stop_id: int
    name: str
    lat: float
    lon: float
    route_ids: list[int]
    transfers: list[tuple[int, int]]  # (target_stop, walk_time_seconds)


@dataclass
class RouteInfo:
    """Original GTFS route information."""
    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int


@dataclass
class Trip:
    trip_id: int
    arrival_times: list[int]  # One per stop in route


@dataclass
class Route:
    route_id: int
    stop_ids: list[int]
    trips: list[Trip]


def load_stops(stops_path: Path, route_id_to_idx: dict[int, list[int]]) -> dict[int, Stop]:
    """Load all stops from stops.bin."""
    stops = {}
    with open(stops_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RSTS":
            raise ValueError(f"Invalid stops.bin magic: {magic}")
        schema_version = reader.read_uint16()
        stop_count = reader.read_uint32()

        for _ in range(stop_count):
            stop_id = reader.read_uint32()
            name = reader.read_string()
            lat = reader.read_float64()
            lon = reader.read_float64()
            num_routes = reader.read_uint32()
            route_ids_internal = [reader.read_uint32() for _ in range(num_routes)]
            num_transfers = reader.read_uint32()
            transfers = []
            for _ in range(num_transfers):
                target = reader.read_uint32()
                walk_time = reader.read_int32()
                transfers.append((target, walk_time))

            # Convert route_id_internal to route_idx
            route_indices = []
            for rid in route_ids_internal:
                if rid in route_id_to_idx:
                    route_indices.extend(route_id_to_idx[rid])

            stops[stop_id] = Stop(stop_id, name, lat, lon, route_indices, transfers)

    return stops


def load_routes(routes_path: Path) -> tuple[dict[int, Route], dict[int, int]]:
    """Load all routes from routes.bin. Returns (routes_dict, route_id_to_idx_mapping)."""
    routes = {}
    route_id_to_idx = {}
    
    with open(routes_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RRTS":
            raise ValueError(f"Invalid routes.bin magic: {magic}")
        schema_version = reader.read_uint16()
        route_count = reader.read_uint32()

        for route_idx in range(route_count):
            route_id_internal = reader.read_uint32()
            num_stops = reader.read_uint32()
            num_trips = reader.read_uint32()

            stop_ids = [reader.read_uint32() for _ in range(num_stops)]

            trips = []
            for _ in range(num_trips):
                trip_id = reader.read_uint32()
                times_encoded = [reader.read_int32() for _ in range(num_stops)]

                # Decode delta encoding
                times = [times_encoded[0]]
                for i in range(1, len(times_encoded)):
                    times.append(times[i - 1] + times_encoded[i])

                trips.append(Trip(trip_id, times))

            # Use route_idx as key, but keep mapping for index lookups
            routes[route_idx] = Route(route_id_internal, stop_ids, trips)
            
            # Multiple route_idx can map to same route_id_internal
            if route_id_internal not in route_id_to_idx:
                route_id_to_idx[route_id_internal] = []
            route_id_to_idx[route_id_internal].append(route_idx)

    return routes, route_id_to_idx


def load_gtfs_route_names(gtfs_path: Path) -> dict[str, RouteInfo]:
    """Load route names from GTFS routes.txt."""
    route_info = {}
    routes_file = gtfs_path / "routes.txt"
    
    if not routes_file.exists():
        return route_info
    
    with open(routes_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            route_id = row['route_id']
            route_info[route_id] = RouteInfo(
                route_id=route_id,
                route_short_name=row.get('route_short_name', ''),
                route_long_name=row.get('route_long_name', ''),
                route_type=int(row.get('route_type', 0))
            )
    
    return route_info


def load_gtfs_mapping(gtfs_path: Path) -> dict[int, str]:
    """Create mapping from internal route_id to original GTFS route_id."""
    # Read routes and create stable sorted mapping (same as in gtfs/reader.py)
    routes_file = gtfs_path / "routes.txt"
    if not routes_file.exists():
        return {}
    
    with open(routes_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        route_ids = sorted([row['route_id'] for row in reader])
    
    # Internal IDs are assigned by lexicographic order
    return {i: route_id for i, route_id in enumerate(route_ids)}


def load_index(index_path: Path) -> dict:
    """Load index from index.bin."""
    with open(index_path, "rb") as f:
        reader = BinaryReader(f)
        magic = reader.read_bytes(4)
        if magic != b"RIDX":
            raise ValueError(f"Invalid index.bin magic: {magic}")
        schema_version = reader.read_uint16()
        
        # Read stop_to_routes
        stop_to_routes = {}
        num_stops = reader.read_uint32()
        for _ in range(num_stops):
            stop_id = reader.read_uint32()
            num_routes = reader.read_uint32()
            route_ids = [reader.read_uint32() for _ in range(num_routes)]
            stop_to_routes[stop_id] = route_ids
        
        # Skip route_offsets
        num_route_offsets = reader.read_uint32()
        for _ in range(num_route_offsets):
            reader.read_uint32()  # route_id
            reader.read_bytes(8)  # offset (uint64)
        
        # Skip stop_offsets
        num_stop_offsets = reader.read_uint32()
        for _ in range(num_stop_offsets):
            reader.read_uint32()  # stop_id
            reader.read_bytes(8)  # offset (uint64)
        
        return {"stop_to_routes": stop_to_routes}


def raptor(
    stops: dict[int, Stop],
    routes: dict[int, Route],
    source: int,
    target: int,
    departure_time: int,
    max_rounds: int = 5,
):
    """
    RAPTOR algorithm for journey planning.
    
    Args:
        stops: Dictionary of all stops
        routes: Dictionary of all routes
        source: Source stop ID
        target: Target stop ID
        departure_time: Departure time in seconds since midnight
        max_rounds: Maximum number of rounds (transfers + 1)
    
    Returns:
        List of journey legs or None if no path found
    """
    INF = float("inf")

    # tau[k][stop] = earliest arrival time at stop with up to k transfers
    tau = [{stop_id: INF for stop_id in stops} for _ in range(max_rounds + 1)]
    tau[0][source] = departure_time

    # parent[k][stop] = (previous_stop, route_id, trip_id) or None for walking
    parent = [{stop_id: None for stop_id in stops} for _ in range(max_rounds + 1)]

    # marked[k] = set of stops improved in round k
    marked = [set() for _ in range(max_rounds + 1)]
    marked[0].add(source)

    for k in range(1, max_rounds + 1):
        # Queue of routes to scan
        routes_to_scan = set()

        # Add routes serving marked stops from previous round
        for stop_id in marked[k - 1]:
            if stop_id in stops:
                for route_id in stops[stop_id].route_ids:
                    routes_to_scan.add(route_id)

        # Scan each route
        for route_id in routes_to_scan:
            route = routes[route_id]

            # Find earliest trip we can board
            earliest_boarding_time = INF
            boarding_stop_idx = None
            best_trip = None

            for stop_idx, stop_id in enumerate(route.stop_ids):
                # Can we board at this stop?
                if tau[k - 1][stop_id] < INF:
                    # Find earliest trip departing after arrival
                    for trip in route.trips:
                        if stop_idx < len(trip.arrival_times) and trip.arrival_times[stop_idx] >= tau[k - 1][stop_id]:
                            if trip.arrival_times[stop_idx] < earliest_boarding_time:
                                earliest_boarding_time = trip.arrival_times[stop_idx]
                                boarding_stop_idx = stop_idx
                                best_trip = trip
                            break  # Trips are sorted, first valid is best

            # If we can board this route, traverse it
            if best_trip is not None:
                boarding_stop_id = route.stop_ids[boarding_stop_idx]
                
                for stop_idx in range(boarding_stop_idx, len(route.stop_ids)):
                    stop_id = route.stop_ids[stop_idx]
                    
                    if stop_idx < len(best_trip.arrival_times):
                        arrival_time = best_trip.arrival_times[stop_idx]

                        if arrival_time < tau[k][stop_id]:
                            tau[k][stop_id] = arrival_time
                            parent[k][stop_id] = (
                                boarding_stop_id,
                                route_id,
                                best_trip.trip_id,
                            )
                            marked[k].add(stop_id)

        # Add footpath transfers
        for stop_id in list(marked[k]):
            if stop_id in stops:
                for target_stop, walk_time in stops[stop_id].transfers:
                    arrival_time = tau[k][stop_id] + walk_time
                    if arrival_time < tau[k][target_stop]:
                        tau[k][target_stop] = arrival_time
                        parent[k][target_stop] = (stop_id, None, None)  # Walking
                        marked[k].add(target_stop)

    # Find best round reaching target
    best_round = None
    best_time = INF
    for k in range(max_rounds + 1):
        if tau[k][target] < best_time:
            best_time = tau[k][target]
            best_round = k

    if best_round is None or best_time == INF:
        return None

    # Reconstruct path
    journey = []
    current_stop = target
    current_round = best_round

    while current_round > 0 and current_stop != source:
        parent_info = parent[current_round][current_stop]
        if parent_info is None:
            break

        prev_stop, route_id, trip_id = parent_info

        if route_id is None:
            # Walking transfer
            journey.append(
                {
                    "type": "walk",
                    "from_stop": prev_stop,
                    "to_stop": current_stop,
                    "duration": tau[current_round][current_stop]
                    - tau[current_round][prev_stop],
                }
            )
            current_stop = prev_stop
        else:
            # Transit leg
            route = routes[route_id]
            from_idx = route.stop_ids.index(prev_stop)
            to_idx = route.stop_ids.index(current_stop)

            journey.append(
                {
                    "type": "transit",
                    "route_id": route_id,
                    "trip_id": trip_id,
                    "from_stop": prev_stop,
                    "to_stop": current_stop,
                    "from_idx": from_idx,
                    "to_idx": to_idx,
                    "stops_sequence": route.stop_ids[from_idx : to_idx + 1],
                    "departure": route.trips[0].arrival_times[from_idx],  # Approximation
                    "arrival": tau[current_round][current_stop],
                }
            )
            current_stop = prev_stop
            current_round -= 1

    journey.reverse()
    return journey


def format_time(seconds: int) -> str:
    """Format seconds since midnight to HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two coordinates."""
    import math
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def main():
    data_dir = Path("./raptor_data")
    gtfs_dir = Path.home() / "Downloads" / "GTFS_TCL"

    print("Loading data...")
    routes, route_id_to_idx = load_routes(data_dir / "routes.bin")
    stops = load_stops(data_dir / "stops.bin", route_id_to_idx)
    index = load_index(data_dir / "index.bin")
    
    # Load GTFS route information
    gtfs_route_info = load_gtfs_route_names(gtfs_dir)
    internal_to_gtfs = load_gtfs_mapping(gtfs_dir)

    print(f"Loaded {len(stops)} stops, {len(routes)} routes\n")

    source = 9105
    target = 7588
    departure_time = 9 * 3600  # 09:00:00

    if source not in stops:
        print(f"Error: Source stop #{source} not found")
        return
    if target not in stops:
        print(f"Error: Target stop #{target} not found")
        return

    print(f"Journey from: {stops[source].name} (Stop #{source})")
    print(f"         to: {stops[target].name} (Stop #{target})")
    print(f"  Departure: {format_time(departure_time)}\n")

    # Try to find a journey, retry with later times if needed
    journey = None
    max_attempts = 6
    time_increment = 30 * 60  # 30 minutes
    current_departure = departure_time
    
    for attempt in range(max_attempts):
        if attempt == 0:
            print("Running RAPTOR algorithm...")
        else:
            print(f"No journey found. Trying later departure: {format_time(current_departure)}...")
        
        journey = raptor(stops, routes, source, target, current_departure, max_rounds=5)
        
        if journey is not None:
            if attempt > 0:
                print(f"✅ Journey found with later departure!\n")
            break
        
        current_departure += time_increment
    
    if journey is None:
        print(f"❌ No journey found even with departures up to {format_time(current_departure - time_increment)}")
        print(f"   Try a different departure time or check if the destination is reachable.")
        return
    
    departure_time = current_departure - time_increment  # Update to actual departure used

    print("✅ Journey found!\n")
    print("=" * 80)

    current_time = departure_time
    leg_counter = 1
    
    for i, leg in enumerate(journey, 1):
        if leg["type"] == "walk":
            from_stop = stops[leg["from_stop"]]
            to_stop = stops[leg["to_stop"]]
            duration = leg["duration"]
            print(f"\n🚶 TRANSFER: Walk")
            print(f"   From: {from_stop.name} (Stop #{from_stop.stop_id})")
            print(f"   To:   {to_stop.name} (Stop #{to_stop.stop_id})")
            print(f"   Duration: {duration}s ({duration // 60} min)")
            current_time += duration

        elif leg["type"] == "transit":
            from_stop = stops[leg["from_stop"]]
            to_stop = stops[leg["to_stop"]]
            route_id = leg["route_id"]
            route = routes[route_id]
            route_id_internal = route.route_id
            from_idx = leg["from_idx"]
            to_idx = leg["to_idx"]
            trip_id = leg["trip_id"]
            
            # Get route name from GTFS
            route_name = f"Route {route_id}"
            if route_id_internal in internal_to_gtfs:
                gtfs_route_id = internal_to_gtfs[route_id_internal]
                if gtfs_route_id in gtfs_route_info:
                    info = gtfs_route_info[gtfs_route_id]
                    if info.route_short_name:
                        route_name = f"Line {info.route_short_name}"
                    elif info.route_long_name:
                        route_name = info.route_long_name
            
            # Find the actual trip to get correct times
            trip = None
            for t in route.trips:
                if t.trip_id == trip_id:
                    trip = t
                    break
            
            if trip:
                leg_departure = trip.arrival_times[from_idx]
                leg_arrival = trip.arrival_times[to_idx]
            else:
                leg_departure = leg.get('departure', 0)
                leg_arrival = leg['arrival']
            
            num_stops = len(leg["stops_sequence"])
            
            # Check for backward movement
            target_stop = stops[target]
            dist_start = haversine_distance(from_stop.lat, from_stop.lon, target_stop.lat, target_stop.lon)
            dist_end = haversine_distance(to_stop.lat, to_stop.lon, target_stop.lat, target_stop.lon)
            
            going_backward = dist_end > dist_start + 500  # 500m tolerance
            
            if going_backward and leg_counter == 1:
                # First leg goes backward - suggest alternatives
                alternatives = [s for s in stops.values() 
                               if s.name == from_stop.name and s.stop_id != from_stop.stop_id]
                
                print(f"\n⚠️  WARNING: First leg goes away from destination (wrong direction)!")
                print(f"\n   💡 SUGGESTIONS:")
                print(f"   1. Wait for a later departure with buses going in the right direction")
                if alternatives:
                    print(f"   2. Start from a nearby stop on the other side of the street:")
                    for alt in alternatives[:3]:
                        alt_routes = [routes[rid].route_id for rid in alt.route_ids[:5]]
                        alt_route_names = []
                        for rid in alt_routes:
                            if rid in internal_to_gtfs:
                                gtfs_id = internal_to_gtfs[rid]
                                if gtfs_id in gtfs_route_info:
                                    info = gtfs_route_info[gtfs_id]
                                    if info.route_short_name:
                                        alt_route_names.append(info.route_short_name)
                        if alt_route_names:
                            print(f"      → Stop #{alt.stop_id} ({alt.name}): Lines {', '.join(alt_route_names[:5])}")

            print(f"\n🚌 LEG {leg_counter}: {route_name}")
            leg_counter += 1
            print(f"   Board at: {from_stop.name}")
            print(f"   Alight at: {to_stop.name}")
            print(f"   Departure: {format_time(leg_departure)}")
            print(f"   Arrival: {format_time(leg_arrival)}")
            print(f"   Duration: {(leg_arrival - leg_departure) // 60} min")
            print(f"   Stops: {num_stops}")

            if num_stops <= 10:
                print(f"   Stops sequence:")
                for stop_id in leg["stops_sequence"]:
                    print(f"     • {stops[stop_id].name}")
            else:
                print(f"   Stops sequence (showing first 5 and last 5):")
                for stop_id in leg["stops_sequence"][:5]:
                    print(f"     • {stops[stop_id].name}")
                print(f"     ... ({num_stops - 10} more stops)")
                for stop_id in leg["stops_sequence"][-5:]:
                    print(f"     • {stops[stop_id].name}")

            current_time = leg_arrival

    print("\n" + "=" * 80)
    total_duration = current_time - departure_time
    print(f"\nTotal journey time: {total_duration // 60} minutes")
    print(f"Arrival time: {format_time(current_time)}")


if __name__ == "__main__":
    main()
