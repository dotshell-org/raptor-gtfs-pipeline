# Raptor GTFS Pipeline

Convert GTFS datasets to compact binary formats optimized for RAPTOR routing algorithm.

## Installation

```bash
make install
```

## Quick Start

Simply convert a GTFS dataset (ZIP file or directory) to binary format:

```bash
make run GTFS=path/to/gtfs.zip
```

This will:
- Extract the GTFS data if it's a ZIP file
- Convert it to binary format
- Generate optimized files in `./raptor_data/`

Examples:
```bash
make run GTFS=~/Downloads/GTFS_TCL.zip
make run GTFS=./gtfs_directory/
```

## Binary Format Specification

### routes.bin

```
Header:
  magic: b"RRTS" (4 bytes)
  schema_version: uint16
  route_count: uint32

For each route:
  route_id: uint32
  stop_count: uint32
  trip_count: uint32
  stop_ids: stop_count × uint32
  trips:
    For each trip:
      trip_id: uint32
      arrival_times: stop_count × int32 (delta-encoded)
```

### stops.bin

```
Header:
  magic: b"RSTS" (4 bytes)
  schema_version: uint16
  stop_count: uint32

For each stop:
  stop_id: uint32
  name_length: uint16
  name: UTF-8 bytes
  lat: float64
  lon: float64
  route_ref_count: uint32
  route_ids: route_ref_count × uint32
  transfer_count: uint32
  transfers:
    For each transfer:
      target_stop_id: uint32
      walk_time: int32
```

### index.bin

```
Header:
  magic: b"RIDX" (4 bytes)
  schema_version: uint16

stop_to_routes:
  pairs_count: uint32
  For each pair:
    stop_id: uint32
    route_count: uint32
    route_ids: route_count × uint32

route_offsets:
  count: uint32
  For each route:
    route_id: uint32
    offset: uint64

stop_offsets:
  count: uint32
  For each stop:
    stop_id: uint32
    offset: uint64
```

All integers use little-endian encoding.

### manifest.json

Contains metadata, checksums, and statistics:

```json
{
  "schema_version": 1,
  "tool_version": "0.1.0",
  "created_at": "2024-12-06T...",
  "inputs": {"gtfs_path": "..."},
  "outputs": {
    "routes.bin": "sha256...",
    "stops.bin": "sha256...",
    "index.bin": "sha256..."
  },
  "stats": {
    "stops": 1234,
    "routes": 56,
    "trips": 789,
    "stop_times": 12345,
    "transfers": 678
  },
  "build": {
    "python": "3.11.0",
    "platform": "Linux-..."
  }
}
```

## Development

### Setup

```bash
make install
```

### Advanced Usage (CLI)

For advanced configuration, use the CLI directly:

```bash
python -m raptor_pipeline.cli convert --input /path/to/gtfs --output ./raptor_data
```
