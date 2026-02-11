#!/usr/bin/env python3
"""
Script de test pour vérifier les horaires d'un arrêt dans tous les dossiers de périodes.
Usage: python check_stop_schedules.py
"""

import struct
from pathlib import Path


def read_uint16(f):
    return struct.unpack("<H", f.read(2))[0]


def read_uint32(f):
    return struct.unpack("<I", f.read(4))[0]


def read_int32(f):
    return struct.unpack("<i", f.read(4))[0]


def read_float64(f):
    return struct.unpack("<d", f.read(8))[0]


def read_string(f):
    length = read_uint16(f)
    return f.read(length).decode("utf-8")


def seconds_to_time(seconds):
    """Convert seconds since midnight to HH:MM:SS format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def read_stops(stops_path):
    """Read stops from stops.bin and return as dict."""
    stops = {}
    with open(stops_path, "rb") as f:
        magic = f.read(4)
        if magic != b"RST2":
            raise ValueError(f"Invalid stops.bin magic: {magic}")
        
        schema_version = read_uint16(f)
        stop_count = read_uint32(f)
        
        for _ in range(stop_count):
            stop_id = read_uint32(f)
            name = read_string(f)
            lat = read_float64(f)
            lon = read_float64(f)
            
            # Read route references
            route_count = read_uint32(f)
            route_ids = [read_uint32(f) for _ in range(route_count)]
            
            # Read transfers
            transfer_count = read_uint32(f)
            for _ in range(transfer_count):
                read_uint32(f)  # target_stop
                read_int32(f)   # walk_time
            
            stops[stop_id] = {
                "id": stop_id,
                "name": name,
                "lat": lat,
                "lon": lon,
                "route_ids": route_ids,
            }
    
    return stops


def read_routes(routes_path):
    """Read routes from routes.bin and return as list (not dict to avoid ID collisions)."""
    routes = []
    with open(routes_path, "rb") as f:
        magic = f.read(4)
        if magic != b"RRT2":
            raise ValueError(f"Invalid routes.bin magic: {magic}")

        schema_version = read_uint16(f)
        route_count = read_uint32(f)

        for route_idx in range(route_count):
            route_id = read_uint32(f)
            route_name = read_string(f)
            stop_count = read_uint32(f)
            trip_count = read_uint32(f)

            stop_ids = [read_uint32(f) for _ in range(stop_count)]

            # v2: read all trip IDs as a block
            trip_ids = [read_uint32(f) for _ in range(trip_count)]

            # v2: read all stop times as a flat block (row-major)
            trips = []
            for i in range(trip_count):
                times = []
                cumulative = 0
                for _ in range(stop_count):
                    delta = read_int32(f)
                    if len(times) == 0:
                        cumulative = delta
                    else:
                        cumulative += delta
                    times.append(cumulative)

                trips.append({
                    "trip_id": trip_ids[i],
                    "times": times,
                })
            
            routes.append({
                "index": route_idx,
                "id": route_id,
                "name": route_name,
                "stop_ids": stop_ids,
                "trips": trips,
            })
    
    return routes


def find_stop_by_name(stops, stop_name):
    """Find stops that match the given name (case-insensitive, partial match)."""
    stop_name_lower = stop_name.lower()
    matches = []
    for stop_id, stop in stops.items():
        if stop_name_lower in stop["name"].lower():
            matches.append(stop)
    return matches


def get_stop_schedules(stops, routes, stop_name):
    """Get all schedules for a specific stop."""
    # Find the stop
    matching_stops = find_stop_by_name(stops, stop_name)
    
    if not matching_stops:
        print(f"❌ Stop '{stop_name}' not found")
        return None
    
    if len(matching_stops) > 1:
        print(f"⚠️  Found {len(matching_stops)} stops matching '{stop_name}':")
        for stop in matching_stops:
            print(f"   - {stop['name']} (ID: {stop['id']})")
        print(f"\nUsing first match: {matching_stops[0]['name']}")
    
    target_stop = matching_stops[0]
    stop_id = target_stop["id"]
    
    # Build route lookup by internal ID (routes is now a list)
    routes_by_id = {}
    for route in routes:
        route_id = route["id"]
        if route_id not in routes_by_id:
            routes_by_id[route_id] = []
        routes_by_id[route_id].append(route)
    
    # Collect all trips passing through this stop
    schedules = []
    
    for route_id in target_stop["route_ids"]:
        if route_id not in routes_by_id:
            continue
        
        # Handle multiple routes with same ID (variants)
        for route in routes_by_id[route_id]:
            # Find position of this stop in route
            try:
                stop_index = route["stop_ids"].index(stop_id)
            except ValueError:
                continue
            
            # Get all trip times for this stop
            for trip in route["trips"]:
                arrival_time = trip["times"][stop_index]
                schedules.append({
                    "route": route["name"],
                    "time": arrival_time,
                    "time_str": seconds_to_time(arrival_time),
                })
    
    # Sort by time
    schedules.sort(key=lambda x: x["time"])
    
    return target_stop, schedules


def format_schedules_table(schedules):
    """Format schedules as a table grouped by hour."""
    if not schedules:
        return "Aucun horaire"
    
    # Group schedules by route and hour
    schedules_by_hour = {}
    for schedule in schedules:
        hour = schedule["time"] // 3600
        if hour not in schedules_by_hour:
            schedules_by_hour[hour] = []
        schedules_by_hour[hour].append(schedule)
    
    # Get unique routes sorted
    unique_routes = sorted(set(s["route"] for s in schedules))
    
    # Calculate actual column width based on content
    max_minutes_per_route = {}
    for route in unique_routes:
        max_len = len(route)
        for hour_schedules in schedules_by_hour.values():
            by_route = [s for s in hour_schedules if s["route"] == route]
            if by_route:
                minutes_list = [f"{(s['time'] % 3600) // 60:02d}" for s in by_route]
                minutes_str = ','.join(minutes_list)
                max_len = max(max_len, len(minutes_str))
        max_minutes_per_route[route] = max_len + 2
    
    # Build table
    lines = []
    lines.append(f"\nLignes: {', '.join(unique_routes)}")
    lines.append(f"\n{'Heure':<8} " + "  ".join(f"{route:^{max_minutes_per_route[route]}}" for route in unique_routes))
    lines.append("=" * (10 + sum(max_minutes_per_route.values()) + 2 * len(unique_routes)))
    
    for hour in sorted(schedules_by_hour.keys()):
        hour_schedules = schedules_by_hour[hour]
        
        # Group by route for this hour
        by_route = {route: [] for route in unique_routes}
        for schedule in hour_schedules:
            minutes = (schedule["time"] % 3600) // 60
            by_route[schedule["route"]].append(f"{minutes:02d}")
        
        # Display hour line
        hour_str = f"{hour:02d}h"
        route_strs = []
        for route in unique_routes:
            col_width = max_minutes_per_route[route]
            if by_route[route]:
                minutes_str = ','.join(by_route[route])
                route_strs.append(f"{minutes_str:<{col_width}}")
            else:
                route_strs.append("-" * col_width)
        
        lines.append(f"{hour_str:<8} " + "  ".join(route_strs))
    
    return "\n".join(lines)


def analyze_period(period_path, stop_name):
    """Analyze schedules for a specific period."""
    stops_path = period_path / "stops.bin"
    routes_path = period_path / "routes.bin"
    
    if not stops_path.exists() or not routes_path.exists():
        print(f"⚠️  Missing files in {period_path.name}")
        return
    
    print(f"\n{'=' * 70}")
    print(f"{period_path.name.upper().replace('_', ' ')}")
    print(f"{'=' * 70}")
    
    # Read data
    stops = read_stops(stops_path)
    routes = read_routes(routes_path)
    
    # Get schedules
    result = get_stop_schedules(stops, routes, stop_name)
    
    if result is None:
        return
    
    target_stop, schedules = result
    
    print(f"Arrêt: {target_stop['name']}")
    
    if schedules:
        print(format_schedules_table(schedules))
        print(f"\nTotal: {len(schedules)} passages")
    else:
        print("\nAucun horaire pour cet arrêt")


def main():
    raptor_data = Path("./raptor_data")
    stop_name = "La Vallonnière"  # Test stop with multiple routes
    
    if not raptor_data.exists():
        print(f"❌ Directory not found: {raptor_data}")
        return
    
    print(f"Arrêt: {stop_name}\n")
    
    # Find all period directories
    period_dirs = []
    for item in raptor_data.iterdir():
        if item.is_dir() and (item / "stops.bin").exists():
            period_dirs.append(item)
    
    period_dirs.sort()
    
    if not period_dirs:
        print("❌ No period directories found in raptor_data/")
        return
    
    # Analyze each period
    for period_dir in period_dirs:
        analyze_period(period_dir, stop_name)


if __name__ == "__main__":
    main()
