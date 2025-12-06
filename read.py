from pathlib import Path
from raptor_pipeline.output.binary import BinaryReader

print("=== LECTURE CORRECTE DES ROUTES ===\n")

routes_path = Path("./raptor_data/routes.bin")
with open(routes_path, "rb") as f:
    reader = BinaryReader(f)
    
    magic = reader.read_bytes(4)
    schema_version = reader.read_uint16()
    route_count = reader.read_uint32()
    print(f"Magic: {magic}, Schema: {schema_version}")
    print(f"Routes: {route_count}\n")
    
    for route_idx in range(min(route_count, route_count)):
        route_id_internal = reader.read_uint32()
        num_stops = reader.read_uint32()
        num_trips = reader.read_uint32()
        
        print(f"Route #{route_idx} (internal_id={route_id_internal}):")
        print(f"  Stops: {num_stops}, Trips: {num_trips}")
        
        stop_ids = []
        for _ in range(num_stops):
            stop_id = reader.read_uint32()
            stop_ids.append(stop_id)
        print(f"  Stop IDs: {stop_ids[:5]}{'...' if len(stop_ids) > 5 else ''}")
        
        for trip_idx in range(min(2, num_trips)):
            trip_id_internal = reader.read_uint32()
            
            times = []
            for _ in range(num_stops):
                time_val = reader.read_int32()
                times.append(time_val)
            
            decoded_times = [times[0]]
            for i in range(1, len(times)):
                decoded_times.append(decoded_times[-1] + times[i])
            
            times_hms = []
            for t in decoded_times[:5]:
                h = t // 3600
                m = (t % 3600) // 60
                s = t % 60
                times_hms.append(f"{h:02d}:{m:02d}:{s:02d}")
            
            print(f"    Trip {trip_id_internal}: {times_hms}...")
        
        remaining_trips = num_trips - min(2, num_trips)
        for _ in range(remaining_trips):
            reader.read_uint32()  # trip_id
            for _ in range(num_stops):
                reader.read_int32()  # time
        
        print()

print("\n=== STOPS ===\n")

stops_path = Path("./raptor_data/stops.bin")
with open(stops_path, "rb") as f:
    reader = BinaryReader(f)
    
    magic = reader.read_bytes(4)
    schema_version = reader.read_uint16()
    stop_count = reader.read_uint32()
    print(f"Magic: {magic}, Schema: {schema_version}")
    print(f"Stops: {stop_count}\n")
    
    for i in range(min(stop_count, stop_count)):
        stop_id_internal = reader.read_uint32()
        name = reader.read_string()
        lat = reader.read_float64()
        lon = reader.read_float64()
        num_routes = reader.read_uint32()
        
        # Lire route refs
        route_refs = [reader.read_uint32() for _ in range(num_routes)]
        
        # Lire transfers
        num_transfers = reader.read_uint32()
        transfers = []
        for _ in range(num_transfers):
            target_stop = reader.read_uint32()
            walk_time = reader.read_int32()
            transfers.append((target_stop, f"{walk_time}s"))
        
        print(f"Stop #{stop_id_internal}: {name}")
        print(f"  Position: {lat:.6f}, {lon:.6f}")
        print(f"  {num_routes} routes: {route_refs[:3]}...")
        if transfers:
            print(f"  Transfers ({num_transfers}):")
            for target, walk_time in transfers:
                print(f"    → Stop #{target} ({walk_time})")
        print()
