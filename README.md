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

## Service Period Splitting

The pipeline can automatically split the output into multiple folders based on service periods (e.g., weekday, saturday, sunday, school holidays). This is useful for reducing the size of routing data when you only need to route for a specific day type.

### Usage

Use the `--split-by-periods` flag:

```bash
python -m raptor_pipeline.cli convert --input /path/to/gtfs --output ./raptor_data --split-by-periods true
```

This will create separate folders:
- `raptor_data/weekday/` - Monday to Friday schedules
- `raptor_data/saturday/` - Saturday schedules  
- `raptor_data/sunday/` - Sunday and holiday schedules
- `raptor_data/weekend/` - Weekend schedules (if applicable)
- `raptor_data/daily/` - Daily schedules (if applicable)
- `raptor_data/custom_N/` - Custom patterns (if applicable)

Each folder contains its own set of binary files (routes.bin, stops.bin, index.bin, manifest.json) with only the trips that operate during that service period.

### How it works

The pipeline:
1. Reads `calendar.txt` and `calendar_dates.txt` from your GTFS feed
2. Groups services by their day-of-week patterns (Monday-Friday, Saturday, Sunday, etc.)
3. Filters trips based on their `service_id`
4. Generates separate binary outputs for each period

### Benefits

- **Smaller files**: Each period only contains relevant trips
- **Faster routing**: Less data to load and process
- **Clear separation**: Easy to select the right data for a given day
- **Flexible**: Automatically adapts to your GTFS calendar structure

## Binary Format Specification

### routes.bin (v2)

```
Header:
  magic: b"RRT2" (4 bytes)
  schema_version: uint16 (= 2)
  route_count: uint32

For each route:
  route_id: uint32
  name_length: uint16
  name: UTF-8 bytes
  stop_count: uint32
  trip_count: uint32
  stop_ids: stop_count × uint32
  trip_ids: trip_count × uint32
  flat_stop_times: (trip_count × stop_count) × int32 (delta-encoded, row-major)

Trips are pre-sorted by departure time at first stop (ascending).
Delta encoding: per trip row, first value is absolute, subsequent values are deltas.
```

### stops.bin (v2)

```
Header:
  magic: b"RST2" (4 bytes)
  schema_version: uint16 (= 2)
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
  "schema_version": 2,
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
