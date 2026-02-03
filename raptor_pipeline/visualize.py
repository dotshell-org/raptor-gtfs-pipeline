"""Generate an HTML map visualization from RAPTOR binary data."""

import argparse
import struct
from pathlib import Path


def read_uint16(f):
    return struct.unpack("<H", f.read(2))[0]


def read_uint32(f):
    return struct.unpack("<I", f.read(4))[0]


def read_float64(f):
    return struct.unpack("<d", f.read(8))[0]


def read_string(f):
    length = read_uint16(f)
    return f.read(length).decode("utf-8")


def read_stops(stops_path: Path) -> list[dict]:
    """Read stops from stops.bin."""
    stops = []
    with open(stops_path, "rb") as f:
        magic = f.read(4)
        if magic != b"RSTS":
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
            transfers = []
            for _ in range(transfer_count):
                target_stop = read_uint32(f)
                walk_time = struct.unpack("<i", f.read(4))[0]
                transfers.append((target_stop, walk_time))
            
            stops.append({
                "id": stop_id,
                "name": name,
                "lat": lat,
                "lon": lon,
                "route_ids": route_ids,
                "transfers": transfers,
            })
    
    return stops


def read_routes(routes_path: Path) -> list[dict]:
    """Read routes from routes.bin."""
    routes = []
    with open(routes_path, "rb") as f:
        magic = f.read(4)
        if magic != b"RRTS":
            raise ValueError(f"Invalid routes.bin magic: {magic}")
        
        schema_version = read_uint16(f)
        route_count = read_uint32(f)
        
        for _ in range(route_count):
            route_id = read_uint32(f)
            route_name = read_string(f)
            stop_count = read_uint32(f)
            trip_count = read_uint32(f)
            
            stop_ids = [read_uint32(f) for _ in range(stop_count)]
            
            # Skip trip data (we only need stop sequences for the graph)
            for _ in range(trip_count):
                _trip_id = read_uint32(f)
                # Read arrival times (delta-encoded int32)
                for _ in range(stop_count):
                    struct.unpack("<i", f.read(4))[0]
            
            routes.append({
                "id": route_id,
                "name": route_name,
                "stop_ids": stop_ids,
            })
    
    return routes


def generate_html_map(stops: list[dict], routes: list[dict], output_path: Path) -> None:
    """Generate an HTML map with the network."""
    
    # Calculate center of the network
    if not stops:
        raise ValueError("No stops found in data")
    
    center_lat = sum(s["lat"] for s in stops) / len(stops)
    center_lon = sum(s["lon"] for s in stops) / len(stops)
    
    # Build stop lookup
    stop_by_id = {s["id"]: s for s in stops}
    
    # Generate colors for routes
    colors = [
        "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
        "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
        "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
        "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
    ]
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>RAPTOR Network Map</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; }}
        .info-panel {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            max-width: 300px;
        }}
        .info-panel h3 {{ margin: 0 0 10px 0; }}
        .stat {{ margin: 5px 0; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="info-panel">
        <h3>🚌 RAPTOR Network</h3>
        <div class="stat"><strong>Stops:</strong> {len(stops)}</div>
        <div class="stat"><strong>Routes:</strong> {len(routes)}</div>
    </div>
    <script>
        var map = L.map('map').setView([{center_lat}, {center_lon}], 12);
        
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);
        
        // Stops
        var stops = {{}};
"""
    
    # Add stops as markers
    for stop in stops:
        popup = f"{stop['name']} (ID: {stop['id']})"
        html += f"""
        stops[{stop['id']}] = L.circleMarker([{stop['lat']}, {stop['lon']}], {{
            radius: 5,
            fillColor: '#3388ff',
            color: '#fff',
            weight: 1,
            opacity: 1,
            fillOpacity: 0.8
        }}).bindPopup("{popup.replace('"', '\\"')}").addTo(map);
"""
    
    # Add route lines
    for i, route in enumerate(routes):
        color = colors[i % len(colors)]
        coords = []
        for stop_id in route["stop_ids"]:
            if stop_id in stop_by_id:
                s = stop_by_id[stop_id]
                coords.append(f"[{s['lat']}, {s['lon']}]")
        
        if len(coords) >= 2:
            route_name = route['name'].replace('"', '\\"').replace("'", "\\'")
            html += f"""
        L.polyline([{', '.join(coords)}], {{
            color: '{color}',
            weight: 3,
            opacity: 0.7
        }}).bindPopup("{route_name}").addTo(map);
"""
    
    # Add transfer lines (dashed)
    html += """
        // Transfers (walking connections)
"""
    for stop in stops:
        for target_id, walk_time in stop["transfers"]:
            if target_id in stop_by_id:
                target = stop_by_id[target_id]
                minutes = walk_time // 60
                html += f"""
        L.polyline([[{stop['lat']}, {stop['lon']}], [{target['lat']}, {target['lon']}]], {{
            color: '#888',
            weight: 1,
            opacity: 0.5,
            dashArray: '5, 5'
        }}).bindPopup("Walk: {minutes} min").addTo(map);
"""
    
    html += """
        // Fit bounds to all stops
        var group = new L.featureGroup(Object.values(stops));
        map.fitBounds(group.getBounds().pad(0.1));
    </script>
</body>
</html>
"""
    
    output_path.write_text(html)
    print(f"Map generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate HTML map from RAPTOR binary data")
    parser.add_argument("--data", required=True, help="Path to raptor_data directory")
    parser.add_argument("--output", default="network_map.html", help="Output HTML file")
    args = parser.parse_args()
    
    data_path = Path(args.data)
    stops_path = data_path / "stops.bin"
    routes_path = data_path / "routes.bin"
    
    if not stops_path.exists():
        raise FileNotFoundError(f"stops.bin not found in {data_path}")
    if not routes_path.exists():
        raise FileNotFoundError(f"routes.bin not found in {data_path}")
    
    print(f"Reading data from {data_path}...")
    stops = read_stops(stops_path)
    routes = read_routes(routes_path)
    
    print(f"Found {len(stops)} stops and {len(routes)} routes")
    
    output_path = Path(args.output)
    generate_html_map(stops, routes, output_path)


if __name__ == "__main__":
    main()
