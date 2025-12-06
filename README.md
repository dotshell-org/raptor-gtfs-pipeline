# Raptor GTFS Pipeline

Convert GTFS datasets to compact binary formats optimized for RAPTOR routing algorithm.

## Installation

```bash
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### Command Line

Convert GTFS to binary format:

```bash
raptor-gtfs convert --input /path/to/gtfs --output ./raptor_data
```

Validate binary output:

```bash
raptor-gtfs validate --input ./raptor_data
```

### Python API

```python
from raptor_pipeline import convert, validate

# Convert
manifest = convert(
    input_path="/path/to/gtfs",
    output_path="./raptor_data"
)

print(f"Converted {manifest.stats['routes']} routes")

# Validate
report = validate(output_path="./raptor_data")
assert report.valid
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

## CLI Options

### Convert

```bash
raptor-gtfs convert [OPTIONS]

Options:
  --input PATH              GTFS directory (required)
  --output PATH             Output directory (default: ./raptor_data)
  --format CHOICE           Output format: binary, json, both (default: binary)
  --compression BOOL        Enable delta encoding (default: true)
  --debug-json BOOL         Generate debug JSON (default: false)
  --gen-transfers BOOL      Generate walking transfers (default: false)
  --allow-partial-trips     Allow trips with missing stops (default: false)
  --speed-walk FLOAT        Walking speed in m/s (default: 1.33)
  --transfer-cutoff INT     Max transfer distance in meters (default: 500)
  --jobs INT                Parallel jobs (default: 1)
  -v, --verbose             Verbose logging
```

### Validate

```bash
raptor-gtfs validate [OPTIONS]

Options:
  --input PATH              Output directory to validate (required)
  -v, --verbose             Verbose logging
```

## Development

### Setup

```bash
make install
```

### Testing

```bash
make test          # Run all tests
make bench         # Run benchmarks
make lint          # Check code style
make typecheck     # Run mypy
make format        # Format code
```

### Code Quality

- **Linting**: ruff (E, F, I, UP, ANN, RUF rules)
- **Formatting**: black (line length 100)
- **Type checking**: mypy strict mode
- **Testing**: pytest with benchmarks

## Performance

Target: < 2s for typical GTFS feed (~100k stop_times) on modern hardware.

Benchmarks on test fixtures (run `make bench`):
- Minimal fixture (6 stop_times): < 0.1s
- Branching fixture (5 stop_times): < 0.1s

## Compatibility

- Python >= 3.11
- Schema version: 1 (current)
- Binary format is platform-independent (little-endian)

## Validation

The validator checks:

**Hard errors** (conversion fails):
- Invalid coordinates (lat/lon out of bounds)
- Unordered stop sequences
- Missing required times
- Orphaned references (trips → routes, stops)

**Warnings** (conversion succeeds):
- Non-increasing trip times
- Extreme transfer times
- Empty stop names
