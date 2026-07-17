# Raptor GTFS Pipeline

Convert GTFS datasets to compact binary formats optimized for the RAPTOR routing algorithm. This project has been fully migrated to Kotlin to provide excellent memory management, high parsing speed through streaming, and robust type safety.

## Requirements

- Java 17 or higher
- Gradle (provided via wrapper `./gradlew`)

## Quick Start

Simply convert a GTFS dataset (ZIP file or directory) to binary format using the Gradle wrapper:

```bash
./gradlew run --args="convert --input /path/to/gtfs.zip"
```

This will:
- Extract the GTFS data if it's a ZIP file
- Stream the CSVs (avoiding `OutOfMemoryError` on large datasets like TCL)
- Convert it to binary format
- Generate optimized files in `./raptor_data/`

Examples:
```bash
./gradlew run --args="convert --input ~/Downloads/GTFS_TCL.zip"
./gradlew run --args="convert --input ./gtfs_directory/"
```

## Service Period Splitting

The pipeline can automatically split the output into multiple folders based on service periods (e.g., weekday, saturday, sunday, school holidays). This is useful for reducing the size of routing data when you only need to route for a specific day type.

### Usage

Use the `--split-by-periods` flag:

```bash
./gradlew run --args="convert --input /path/to/gtfs --output ./raptor_data --split-by-periods true"
```

This will create separate folders:
- `raptor_data/weekday/` - Monday to Friday schedules
- `raptor_data/saturday/` - Saturday schedules  
- `raptor_data/sunday/` - Sunday and holiday schedules
- `raptor_data/weekend/` - Weekend schedules (if applicable)
- `raptor_data/daily/` - Daily schedules (if applicable)
- `raptor_data/other/` - Any services that don't match a standard day-type

Each folder contains its own set of binary files (`routes.bin`, `stops.bin`, `index.bin`, `manifest.json`) with only the trips that operate during that service period.

### Preview the plan (`--dry-run`)

See exactly which period folders would be produced — without writing anything:

```bash
./gradlew run --args="convert --input /path/to/gtfs --split-by-periods true --dry-run"
```

### Profiles (`--profile`)

A **declarative YAML profile** lets you say precisely which services go into which period:

```bash
./gradlew run --args="convert --input /path/to/gtfs --profile profiles/marseille.yaml"
```

## Dataset index (`dataset.json`)

Every run writes a self-describing `dataset.json` at the output root, so a consumer can discover what was produced without guessing folder names.

<details>
<summary>Show manifest.json example</summary>

```json
{
  "schema_version": 2,
  "tool_version": "1.0.0",
  "created_at": "2026-07-17T12:00:00Z",
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
    "java": "17.0.2",
    "platform": "Mac OS X"
  }
}
```

</details>

## Binary Format Specification

*No changes to the v2 binary specification during the Kotlin migration. See existing specs for binary chunk layout.*

## Development

```bash
./gradlew build
./gradlew test
```
