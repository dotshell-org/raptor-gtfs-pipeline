# Whole-France GTFS benchmark

**Question:** can [raptor-kmp](https://github.com/dotshell-org/raptor-kmp) route over a GTFS
covering all of mainland France, on a phone and on a server?

The pipeline converts one feed per run. Answering the question takes an input it has never
seen: every reasonably complete French feed, merged into one. This folder builds that input,
converts it with the pipeline as usual, and measures the engine on it.

## How it is built

The merge is done in nested tiers, so every measurement sits on a size curve rather than
being a single point:

| Tier | Count | Example |
|---|---|---|
| Métropole | the 22 legal métropoles | Lyon: TCL |
| Région | the 13 mainland regions | Auvergne-Rhône-Alpes: TCL, STAS, M TAG, Cars Région, TER… |
| France | 1 | every included feed |

Overseas regions are left out. They run on other time zones and are linked to nothing on the
mainland, so they would only add volume.

There are two data layers:

- **Regional:** urban, interurban and TER. At this layer the France tier is the regions side by
  side, joined only by the TER lines that cross regional borders.
- **Long distance:** TGV INOUI, OUIGO, Intercités, international trains, long-distance coaches
  and island ferries. Added last, together with station matching and a connectivity audit.
  Comparing the two layers shows what a connected France costs the engine.

## Steps

| # | Step | Where | Status |
|---|---|---|---|
| 0 | Scaffold | this folder | done |
| 1 | Feed catalogue | `catalog/` | done |
| 2 | Download latest versions, credentials | `gtfs_bench/download.py` | done |
| 3 | Merge N feeds into one per tier | `gtfs_bench/` + `tests/` | done |
| 4 | Notebook running the whole chain | `notebooks/gtfs_france.ipynb` | done |
| 5 | Pipeline conversion, measured | `gtfs_bench/convert.py` | in review |
| 6 | Engine harness (`:benchmark-engine`) | `engine/` | |
| 7 | Report | `RESULTS.md` | |
| 8 | Long-distance layer, connected France | catalogue + `gtfs_bench/connectivity.py` | |

## Setup

Python 3.14 with wheels only (no compiler needed). From this folder:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt       # Linux / macOS
```

## Running it

`notebooks/gtfs_france.ipynb` runs the whole chain, top to bottom:

1. configuration;
2. credentials;
3. catalogue summary;
4. download;
5. choice of the reference day;
6. normalization;
7. merge of the 22 métropoles, the 13 regions and France;
8. tier statistics;
9. checks;
10. conversion of every tier by the pipeline.

**Building the pipeline needs JDK 21.** Kotlin 2.1.0 cannot parse Java 25's version string,
so `./gradlew` fails with an internal compiler error when the Gradle daemon runs on JDK 25.
Point `JAVA_HOME` at a JDK 21, for instance the one Gradle provisions for the toolchain:

```bash
JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 ./gradlew :cli:installDist
```

The notebook runs the pipeline with the same `JAVA_HOME`.

Open it with the `.venv` interpreter as kernel, or run it headless from `notebooks/`:

```bash
../.venv/Scripts/python -m jupyter nbconvert --to notebook --execute gtfs_france.ipynb --output gtfs_france.out.ipynb
```

The notebook is committed without outputs. What it measures lands in `results/`:

| File | Contents |
|---|---|
| `reference_day.json`, `coverage.csv`, `coverage.png` | how the reference day was chosen |
| `feeds_used.csv` | the sha256 and calendar of every feed version that went in |
| `merge_stats.csv`, `tiers.png` | the size of each tier, over the week and on the reference day |
| `pattern_overlaps.csv` | feeds that run the same stop sequences |
| `pipeline.csv` | per tier: conversion time, peak memory, `.bin` sizes, trips kept |

**The reference day** is the Tuesday, outside school holidays, that the most feeds run
on, then the one with the most trips. It is computed from the downloaded calendars over
the next six weeks. The pipeline converts that one day, and the merge keeps its whole
week.

## Credentials

Most feeds come from [transport.data.gouv.fr](https://transport.data.gouv.fr) and need no
account. The ones that do are marked in the catalogue's `auth` column:

| `auth` | Source | What it needs |
|---|---|---|
| `grandlyon` | Data Grand Lyon, official TCL GTFS | GrandLyon Connect account, HTTP Basic |

To provide them:

1. Copy `.env.example` to `.env` and fill it in. `.env` is ignored by git.
2. If a value is missing there, it is read from the environment.
3. If it is missing from both, the notebook asks for it interactively.

Credentials are never printed or written anywhere else.

## Downloading

```bash
python -m gtfs_bench.download                   # every included feed (6 in parallel)
python -m gtfs_bench.download --feeds tcl,idfm  # a few, included or not
python -m gtfs_bench.download --prompt          # ask for missing credentials
```

Each feed lands in `data/raw/<feed_id>.zip` and is unpacked into `data/extracted/<feed_id>/`.
`data/raw/manifest.csv` records, for each feed:

- what was fetched and from where, with its sha256;
- the dates its calendars cover;
- for a failure, what went wrong and what to try.

A rerun only fetches what changed. The previous ETag / Last-Modified are sent as a
conditional GET, and a 304 keeps the file on disk.

Downloads are treated as untrusted:

- each one goes to a temporary name;
- it must be a zip holding one GTFS feed before it replaces the previous version;
- a zip that only wraps another zip is unwrapped;
- extraction keeps only the feed's `.txt` files, flattened, so no entry can land outside
  its folder.

A feed the script cannot reach can be placed by hand at `data/raw/<feed_id>.zip`.
`python -m gtfs_bench.download --register <feed_id>` puts it through the same checks,
unpacks it, and records it as `manual` in the manifest.

## Merging

The merge has two stages: each feed is first normalized on its own, then each tier is
merged from the normalized feeds.

**`normalize.py`, one feed → `data/normalized/<feed_id>/*.parquet`.** This stage settles
what the pipeline would trip over and what two feeds would collide on:

- every id gets the `feed_id:` prefix, references included;
- only physical stops inside mainland France are kept (the pipeline reads neither
  `location_type` nor `parent_station`);
- the catalogue's agency and `stop_id` filters are applied;
- calendars become explicit dates inside the window;
- `frequencies.txt` becomes trips;
- missing times are interpolated along the distance;
- forbidden and trip-to-trip transfers are dropped (the pipeline ignores `transfer_type`).

Results are cached per (source sha256, window, filters), and a `report.json` counts every
drop and its reason.

**`merge.py`, normalized feeds → `data/merged/<tier kind>/<tier>.zip`, one per tier:**

| Tier | Feeds |
|---|---|
| `metropole:<key>` | the rows with that `metropole` |
| `region:<code>` | the rows of that region, plus national rows clipped to it (trips serving ≥ 2 stops inside, cut to them) |
| `france` | every included row |

On top of the union, the merge:

1. drops trips carried by two feeds (same stops to ~10 m, same times, same dates); the
   lower `priority` keeps them;
2. drops orphans;
3. renames stops that share a name across distant places (`names.py`): "Mairie
   (Vénissieux)". raptor-kmp links every pair of same-name stops with a 120 s transfer,
   and across France that would teleport between towns;
4. adds walking transfers between stops less than 300 m apart, at most 30 neighbours,
   both ways (`transfers.py`), on top of the producers' own;
5. checks that every reference resolves before writing the zip.

`merge.pattern_overlaps()` lists the feed pairs that run the same stop sequences, times
ignored. Use it after changing the catalogue: a network carried by two feeds in two
versions of its timetable slips past trip deduplication, which compares times.

The output carries `agency`, `stops`, `routes`, `trips`, `stop_times`,
`calendar_dates` (explicit dates, no `calendar.txt`), `transfers` and `feed_info`, in
`Europe/Paris`. Shapes and fares are not carried: routing does not use them.

Boundaries come from Etalab's 2025 administrative contours, downloaded once into
`data/geo/`.

## Tests

```bash
python -m pytest
```

The tests need no network: downloads are exercised against a local HTTP server.

## Data

Everything downloaded or produced goes under `data/`, which is ignored by git:

| Folder | Contents |
|---|---|
| `raw/` | downloaded zips and their manifest |
| `extracted/` | unzipped feeds |
| `normalized/` | one parquet set per feed |
| `merged/` | one GTFS zip per tier |
| `raptor/` | the pipeline's output |
| `geo/` | administrative boundaries |

None of it is committed. Several source licences (ODbL, Licence Mobilités) put conditions on
redistributing a derived database, and a merged France feed is one. Only measurements
(`results/`) and the report are committed.
