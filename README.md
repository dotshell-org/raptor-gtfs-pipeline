# Raptor GTFS Pipeline

Convert GTFS datasets to compact binary formats optimized for RAPTOR routing algorithm.

## Installation

```bash
uv sync
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
uv run raptor-gtfs convert --input /path/to/gtfs --output ./raptor_data --split-by-periods true
```

This will create separate folders:
- `raptor_data/weekday/` - Monday to Friday schedules
- `raptor_data/saturday/` - Saturday schedules  
- `raptor_data/sunday/` - Sunday and holiday schedules
- `raptor_data/weekend/` - Weekend schedules (if applicable)
- `raptor_data/daily/` - Daily schedules (if applicable)
- `raptor_data/other/` - Any services that don't match a standard day-type
  (a single bucket — the pipeline never emits dozens of numbered `custom_N`
  folders; use a **profile** to classify these precisely)

Each folder contains its own set of binary files (routes.bin, stops.bin, index.bin, manifest.json) with only the trips that operate during that service period.

### Preview the plan (`--dry-run`)

See exactly which period folders would be produced — without writing anything:

```bash
uv run raptor-gtfs convert --input /path/to/gtfs --split-by-periods true --dry-run
```

```
Would generate 4 period folder(s):
  saturday       19 service(s)   13148 trips   Saturday service
  sunday         12 service(s)    7527 trips   Sunday service
  weekday        45 service(s)   20843 trips   Weekday service (Mon–Fri)
  other           7 service(s)    8079 trips   ...
```

### Profiles (`--profile`)

The default splitter groups by exact weekly pattern, so feeds with many quirky
calendars dump everything into `other`. A **declarative YAML profile** lets you
say precisely which services go into which period (implies `--split-by-periods`):

```bash
uv run raptor-gtfs convert --input /path/to/gtfs --profile profiles/marseille.yaml
```

```yaml
# profiles/lyon.yaml — a service matches a period when it satisfies ALL conditions
network: lyon-tcl
periods:
  saturday:            { days: [sat] }
  sunday:              { days: [sun] }
  school_on_weekdays:  { days: [mon-fri], service_id_matches: "-M-$" }
  school_off_weekdays: { days: [mon-fri], service_id_matches: "-[VW]-$" }
unmatched: other       # or "warn" to log & drop unmatched services
```

- `days`: tokens `mon`..`sun`, ranges like `mon-fri`, aliases `weekdays` /
  `weekend` / `daily`. A service matches if it runs on **any** of these days
  (so a Mon–Sat service appears in both `weekday` and `saturday`).
- `service_id_matches`: a regex searched against the `service_id`.
- A service may match several periods. Combine with `--dry-run` to tune a profile
  quickly. See `profiles/lyon.yaml` and `profiles/marseille.yaml`.

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

## Line Geometry (optional)

Add `--traces` to also extract each line's shape as compact binary geometry
(`lines.bin`), on top of the RAPTOR routing data:

```bash
uv run raptor-gtfs convert --input /path/to/gtfs --output ./raptor_data --traces
```

- Reads `shapes.txt`, keeps the **longest shape per direction** for every route,
  and writes a single `lines.bin` at the output root.
- **No-op if the feed has no `shapes.txt`** (a warning is logged; the routing
  data is still produced) — this is why it is opt-in.
- Coordinates are stored as delta-encoded fixed-point integers, so the
  over-sampled shape geometry stays small.

## Dataset index (`dataset.json`)

Every run writes a self-describing `dataset.json` at the output root, so a
consumer can discover what was produced without guessing folder names:

```json
{
  "schema_version": 2,
  "tool_version": "0.2.0",
  "created_at": "...",
  "input": { "gtfs_path": "..." },
  "layout": "flat",              // flat | nested | single
  "lines": { "file": "lines.bin", "coord_scale": 1000000 },  // null if no --traces
  "periods": [
    {
      "name": "saturday",
      "description": "Saturday service",
      "files": {                 // paths relative to the output root
        "routes": "routes_saturday.bin",
        "stops": "stops_saturday.bin",
        "index": "index_saturday.bin"
      },
      "checksums": { "routes_saturday.bin": "sha256…", "…": "…" },
      "stats": { "stops": 2745, "routes": 244, "trips": 20843, "…": 0 }
    }
  ]
}
```

`files` paths adapt to the layout (`routes_saturday.bin` when `--flat`,
`saturday/routes.bin` when nested). Read `dataset.json` to locate each period's
files instead of hardcoding names.

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

### lines.bin (v2, optional — `--traces`)

Written once at the output **root** (line geometry is period-independent, so it
is a sibling of any per-period folders). Only produced when `--traces` is passed
and the feed has a `shapes.txt`.

```
Header:
  magic: b"RLN2" (4 bytes)
  schema_version: uint16 (= 2)
  coord_scale: uint32 (fixed-point divisor, e.g. 1000000)
  line_count: uint32

For each line:
  line_id_internal: uint32          (GTFS route index)
  name_length: uint16 + name: UTF-8 (route_short_name)
  color_length: uint16 + color: UTF-8       (GTFS route_color hex, may be empty)
  text_color_length: uint16 + text_color: UTF-8
  transport_type: uint16            (raw GTFS route_type)
  path_count: uint16                (one path per direction)
  For each path:
    direction_id: uint16
    point_count: uint32
    lon: point_count × int32   (fixed-point round(lon*coord_scale), delta-encoded)
    lat: point_count × int32   (fixed-point round(lat*coord_scale), delta-encoded)

Geometry per line/direction = the longest shape (most points) of that direction.
Delta encoding: first value absolute, subsequent values are deltas. Decode a
coordinate as value / coord_scale. Points are [lon, lat] (GeoJSON axis order).
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

<details>
<summary>Show manifest.json example</summary>

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

</details>

## Development

### Setup

```bash
uv sync
```

### Advanced Usage (CLI)

For advanced configuration, use the CLI directly:

```bash
uv run raptor-gtfs convert --input /path/to/gtfs --output ./raptor_data
```
