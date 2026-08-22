# Raptor GTFS Pipeline

Convert GTFS datasets to compact binary formats optimized for the RAPTOR routing algorithm. This project has been fully migrated to Kotlin to provide excellent memory management, high parsing speed through streaming, and robust type safety.

It ships as two things: a **library** on Maven Central, and the **CLI** built on top of it.

| Module | Artifact | What it is |
|---|---|---|
| `:core` | `eu.dotshell:raptor-gtfs-pipeline` | The conversion, as an API. Depends on no argument parser. |
| `:cli` | *not published* | The `raptor-gtfs-pipeline` command. Flag parsing and nothing else. |

The split is what lets a service — the one that publishes datasets to the apps — drive the
conversion in-process instead of shelling out to a binary and parsing its stdout.

## Requirements

- Java 17 or higher (the library targets 17; the build itself runs on a 21 toolchain)
- Gradle (provided via wrapper `./gradlew`)

## Use it as a library

```kotlin
dependencies {
    implementation("eu.dotshell:raptor-gtfs-pipeline:0.4.0")
}
```

```kotlin
import eu.dotshell.raptor.gtfs.pipeline.ConvertRequest
import eu.dotshell.raptor.gtfs.pipeline.Pipeline
import eu.dotshell.raptor.gtfs.pipeline.PipelineLog
import kotlin.io.path.Path

// The pipeline narrates a long conversion; send that wherever your logs go.
PipelineLog.sink = { line -> logger.info(line) }

val dataset = Pipeline.convert(
    ConvertRequest(
        input = Path("GTFS_TCL.zip"),      // directory or .zip — a zip is extracted and cleaned up
        output = Path("out"),
        profile = Path("profiles/lyon.yaml"),
        sourceLabel = "https://download.example/tcl.zip",  // recorded in dataset.json
    )
)

dataset.schemaVersion        // what a client must be able to parse
dataset.stopsSchemaVersion   // stops evolve on their own version
dataset.validity.endDate     // how long these timetables can be trusted
dataset.periods              // per-period files, checksums and stats
```

`Pipeline.dryRun(request)` reports the period plan without writing anything, and
`Pipeline.readDataset(path)` parses a `dataset.json` back into the same type — a publisher
reads what it just wrote with the pipeline's own model rather than a parser of its own.

## Quick Start

Simply convert a GTFS dataset (ZIP file or directory) to binary format using the Gradle wrapper:

```bash
./gradlew :cli:run --args="convert --input /path/to/gtfs.zip"
```

This will:
- Extract the GTFS data if it's a ZIP file
- Stream the CSVs (avoiding `OutOfMemoryError` on large datasets like TCL)
- Convert it to binary format
- Generate optimized files in `./raptor_data/`

Examples:
```bash
./gradlew :cli:run --args="convert --input ~/Downloads/GTFS_TCL.zip"
./gradlew :cli:run --args="convert --input ./gtfs_directory/"
```

## Service Period Splitting

The pipeline can automatically split the output into multiple folders based on service periods (e.g., weekday, saturday, sunday, school holidays). This is useful for reducing the size of routing data when you only need to route for a specific day type.

### Usage

Use the `--split-by-periods` flag:

```bash
./gradlew :cli:run --args="convert --input /path/to/gtfs --output ./raptor_data --split-by-periods true"
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
./gradlew :cli:run --args="convert --input /path/to/gtfs --split-by-periods true --dry-run"
```

### Profiles (`--profile`)

A **declarative YAML profile** lets you say precisely which services go into which period:

```bash
./gradlew :cli:run --args="convert --input /path/to/gtfs --profile profiles/marseille.yaml"
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
./gradlew build          # both modules
./gradlew :core:test
./gradlew :cli:installDist   # cli/build/install/raptor-gtfs-pipeline/bin/raptor-gtfs-pipeline
```

## Publishing to Maven Central

The version lives in `gradle.properties` alone — `:core` generates `PIPELINE_VERSION` from
it, so the `tool_version` stamped into every `dataset.json` always names the artifact that
produced it. Bump it there and nowhere else.

Credentials never belong in this repository's `gradle.properties`, which is committed. Put
them in `~/.gradle/gradle.properties`:

```properties
ossrhUsername=<Central Portal token name>
ossrhPassword=<Central Portal token>
signing.keyId=<last 8 chars of the GPG key id>
signing.password=<GPG key passphrase>
signing.secretKeyRingFile=/path/to/secring.gpg
```

or in the environment as `OSSRH_USERNAME`, `OSSRH_PASSWORD`, `SIGNING_KEY_ID`,
`SIGNING_PASSWORD` and either `SIGNING_KEY_RING_FILE` or an armoured `SIGNING_KEY` — which
is what CI would use.

```bash
./gradlew :core:publishToMavenLocal                  # verify the artifacts first
./gradlew :core:publishAllPublicationsToCentralPortal
```

The deployment releases automatically once Central's validation passes. Pass
`-PpublishingType=USER_MANAGED` to have it wait in the portal for a manual look instead.

Without signing keys configured the build still works — it simply produces no signatures,
and Central rejects the upload. That is deliberate: a missing key must not fail everyone's
`./gradlew build`.
