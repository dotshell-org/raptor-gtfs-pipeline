# Whole-France GTFS benchmark

**Question:** can [raptor-kmp](https://github.com/dotshell-org/raptor-kmp) route over a GTFS
covering all of mainland France, on a phone and on a server? **Answer so far:** see
[RESULTS.md](RESULTS.md) (in French: [RESULTS.fr.md](RESULTS.fr.md)).

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
| 5 | Pipeline conversion, measured | `gtfs_bench/convert.py` | done |
| 6 | Engine harness (`:benchmark-engine`) | `engine/` + `gtfs_bench/engine.py` | done |
| 7 | Report | [`RESULTS.md`](RESULTS.md) | done |
| 8 | Long-distance layer, connected France | catalogue + `gtfs_bench/connected.py`, `connectivity.py` | done |
| 9 | Address search in the explorer, and its cost | `gtfs_bench/explorer/geocode.py`, harness `--mode points` | done |
| 10 | Every school line, with a switch | catalogue `scolaire` layer, `gtfs_bench/school.py`, explorer | done |
| 11 | Feed horizon, three day types, daily refresh | `gtfs_bench/horizon.py`, `refresh.py`, `refresh.ps1` | done |
| 12 | Engine memory, the network: 275 → 124 MB, fits 224m | raptor-kmp `perf/memory-256`, `gtfs_bench/engines.py` | in review |
| 13 | Engine memory, search state and load peak | raptor-kmp `perf/memory-256` | planned |
| 14 | Report update | `RESULTS.md`, `RESULTS.fr.md` | planned |

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
10. conversion of every tier by the pipeline;
11. raptor-kmp on every tier, and the heap sweep;
12. optionally, France with the producers' stop names (`gtfs_bench/variants.py`);
13. France connexe: the long-distance layer, measured against the regional France
    (`gtfs_bench/connected.py`, see below).

**Building the pipeline needs JDK 21.** Kotlin 2.1.0 cannot parse Java 25's version string,
so `./gradlew` fails with an internal compiler error when the Gradle daemon runs on JDK 25.
Point `JAVA_HOME` at a JDK 21, for instance the one Gradle provisions for the toolchain:

```bash
JAVA_HOME=~/.gradle/jdks/eclipse_adoptium-21-amd64-windows.2 ./gradlew :cli:installDist :benchmark-engine:installDist
```

The notebook runs the pipeline and the engine harness with the same `JAVA_HOME`.

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
| `engine/*.json`, `engine.csv`, `engine_scenarios.csv` | raptor-kmp per tier: load, heap, latency of every query set, named trips |
| `engine_heap.csv` | whether Lyon, AURA, Île-de-France and France load and route under -Xmx 256 MB to 4 GB |
| `engine_local_trips.png`, `engine_heap.png`, `engine_latency.png` | the engine figures |
| `engine_same_name_links.csv` | France with and without the merge's renaming of homonym stops |
| `connected_france.csv`, `connected_scenarios.csv`, `engine/variants/` | France juxtaposée, split per stop sequence, and connexe: pipeline, engine at 5 and 8 rounds, heap checks |
| `connectivity_islands.csv` | the pieces of each network that the rest cannot reach, and why |
| `reachability_prefectures.csv`, `reachability.png` | Paris → every préfecture by raptor-kmp, per network |

**The reference day** is the Tuesday, outside school holidays, that the most feeds run
on, then the one with the most trips. It is computed from the downloaded calendars over
the next six weeks. The pipeline converts that one day, and the merge keeps its whole
week.

## The engine harness

`engine/` is the Gradle module `:benchmark-engine`. It depends on
`eu.dotshell:raptor-kmp-jvm` from Maven Central (2.2.0, the latest JVM release;
`-PraptorKmpVersion=` picks another). It never touches the engine's sources: it times what
an app ships.

`gtfs_bench/engine.py` starts one JVM per tier, so every load is cold, and reads back the
harness's JSON report. Each report holds:

- **load**: reading the files, then deserialization and network construction, forced as
  raptor-kmp's own `LoadBenchmark` does; first in a fresh JVM, then the median of five
  warm loads;
- **heap**: what the loaded network holds once garbage is collected, and the peak during
  the run;
- **query sets**:
  - `random`: 1,000 seeded pairs over all of the tier's stops, as raptor-kmp's
    `RandomQueryGenerator` (departures 6:00–21:59), forward and arrive-by (arrival one
    hour later, default 120 min window);
  - `lyon-local`, `paris-local` (`engine/areas.csv`): 300 seeded trips drawn inside each
    city, every endpoint resolved to the stops within 400 m. The same trips are replayed on
    the métropole, its region and France: what a rider in the city pays for a bigger
    network;
- **named trips** (`engine/scenarios.csv`): from Bellecour → Part-Dieu to Brest →
  Strasbourg, each place being the stops within a radius of its coordinates, so the trip
  reads the same on every tier.

Queries run with the engine's defaults (`maxRounds = 5`, so at most four changes), as the
apps run them. The heap sweep reruns Lyon, Auvergne-Rhône-Alpes, Île-de-France and France
in heap mode (load plus 200 queries) under -Xmx 256m, 384m, 512m, 1g, 2g and 4g.

```bash
python -m gtfs_bench.engine                      # all tiers, then the sweep
python -m gtfs_bench.engine --tiers france --no-sweep
```

These are desktop JVM numbers (JDK 21, Core Ultra 5 135H). A phone runs ART on a slower
core: the heap figures carry over, the times do not.

## France connexe (step 8)

```bash
python -m gtfs_bench.connected                  # ~20 min: two France merges and conversions
python -m gtfs_bench.connected --skip-build     # re-time and re-audit what is converted
```

Two variants of the France tier, each changing one thing, merged into
`data/merged/variants/france/` and converted to `data/raptor/<variant>/`:

- **`france-patterns`:** the regional feeds, with every route split into one route per
  stop sequence (`MergeParams.split_patterns`). The pipeline keeps one sequence per route
  and direction and drops the trips that skip one of its stops; split, it keeps them all.
- **`france-connexe`:** the same, plus the catalogue's `longue_distance` rows and wider
  links around the stations of national networks (`MergeParams.stations`: 500 m and 60
  neighbours from a station's stops, and every pair of SNCF stops sharing a UIC code).
- **`france-complete`** (step 10): france-connexe plus the `scolaire` rows, the 18 feeds
  that carry only school transport (`--variants france-complete`).

Each one, and the regional France as it is, then gets:

- its **school lines** (`gtfs_bench/school.py`): which lines are school lines, by the
  catalogue (`school` column), the GTFS school route types 712/713, the name, or a line
  serving a school with at most 6 runs that day. They go to `school_routes.json` next to the
  `.bin` files, as the route numbers raptor-kmp knows them, checked against the engine's own
  names; the full list for review is `results/school_routes.csv` (per feed:
  `results/school_feeds.csv`). The harness then times the same trips with and without them
  (`--mode school`, `results/school_switch.csv`);

- the engine harness at 5 rounds (the default) and at 8, and heap checks at 384m, 512m
  and 1g;
- a **connectivity audit** (`gtfs_bench/connectivity.py`): connected components of the
  reference day's graph (rides between consecutive stops, transfers), and the islands left
  with the distance to the main network as a hint of why;
- **Paris → every préfecture**: raptor-kmp from Châtelet at 07:00, 8 rounds, to the stops
  near each préfecture's town hall (geo.api.gouv.fr, cached in `data/geo/`).

The explorer opens any of them: `python -m gtfs_bench.explorer --tier france-connexe`.

## Live network: the feeds' horizon, three day types, a daily refresh (step 11)

```bash
python -m gtfs_bench.horizon     # today's window: results/feed_horizon.{csv,png}, results/horizon.json
python -m gtfs_bench.refresh     # download, recompute, rebuild data/raptor/france-live if needed
```

raptor-kmp has no calendar: one network is one day's timetable. Pelo serves TCL, whose file
covers months, with a few day types. For France the file is the sum of 250 producers', and
most publish only a few weeks ahead (IDFM about a month), so:

- **The window** (`gtfs_bench/horizon.py`) runs from today to the day before the first feed
  that matters stops publishing: one carrying more than 0.5 % of the trips, or the one that
  takes the small feeds already stopped past 1 % together. The small ones that stop earlier
  are listed (a ski shuttle between two seasons, a network whose next file is not out yet).
  On 19 November 2026: to 18 December, set by IDFM (27 % of the trips; it had published
  one more day by the evening); six feeds worth 0.28 % stop before.
- **The day types**: the timetables of a Tuesday, a Saturday and a Sunday of the earliest
  week ahead (whole weeks, so the normalized feeds stay cached), plus a holiday Tuesday when
  the window reaches national school holidays (Christmas, summer). A date runs on its day
  type; public holidays run as Sundays, as in Pelo.
- **The live network** `data/raptor/france-live/` holds one folder per day type (the same
  feeds as `france-complete`, the pipeline run with one period per day type), each with its
  `school_routes.json`, plus `horizon.json` (the window) and `refresh.json` (the last run).
- **The daily refresh** (`gtfs_bench/refresh.py`) keeps it ahead: it downloads every feed
  (conditional requests, so an unchanged one costs a round trip; a feed that fails keeps
  its last good file), asks the PAN for newer resources of the feeds about to stop (reported,
  not added: the catalogue stays curated), recomputes the window, and rebuilds only when a
  feed changed or the day types moved. "Changed" means the files inside the zip (names,
  sizes, CRC-32 in `data/raw/content_signatures.json`): several APIs (Cityway, DataSud)
  build the zip afresh at each request, so its bytes change when its timetables do not.
  The new network is built next to the old one and
  swapped in at the end. Its log is `data/logs/refresh-<date>.log`. About 10 minutes and
  10 GB of RAM when it rebuilds.

For the Windows task scheduler, `refresh.ps1` runs it from the venv (`.\refresh.ps1 --force`
passes options on). A daily task at 4:00 that also runs at the next wake-up when the PC
slept through it:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\refresh.ps1`""
Register-ScheduledTask -TaskName "raptor-gtfs-refresh" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 4am) -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable)
```

The benchmark numbers stay those of the reference day (24 November); every result file
from step 11 on says the date of the data it was measured on.

## Engine memory: raptor-kmp on a phone-sized heap (steps 12–13)

The work is in raptor-kmp itself (branch `perf/memory-256` of that repository, version
`2.4.0-SNAPSHOT`); this side compares engine builds on the same networks:

```bash
python -m gtfs_bench.engines publish                          # ../raptor-kmp working copy -> ~/.m2
python -m gtfs_bench.engines install 2.2.0                    # harness on Maven Central's 2.2.0
python -m gtfs_bench.engines install 2.4.0-SNAPSHOT --local   # harness on the local build
python -m gtfs_bench.engines compare 2.2.0 2.4.0-SNAPSHOT     # ~1 h
```

Each harness build lives in `data/tmp/engines/<version>/`; `build/install` keeps the default
engine for the explorer. `-PraptorKmpLocal` adds `mavenLocal()` to the build's repositories
(only then). raptor-kmp's build needs `-Pandroid.builtInKotlin=false -Pandroid.newDsl=false`
with AGP 9 and an Android SDK (`ANDROID_HOME`, default `%LOCALAPPDATA%\Android\Sdk`).

`compare` runs, on Lyon and three France networks:

- **golden journeys** (harness `--mode golden`): every journey of 2,500 fixed queries (random
  stop pairs forward and arrive-by, the Lyon and Paris local sets, addresses forward and
  arrive-by, 200 searches without the school lines), hashed field by field. An optimization
  must give the very same hashes;
- the **retained heap** and the JVM's **class histogram** of the loaded network
  (`results/engine/memory/histogram/`);
- the **full timing run**, and the **smallest heap** (160m, 192m, 224m…) that loads the
  network and answers 200 queries.

Summary in `results/engine_memory.csv`; details in `results/engine/memory/`.

## Explorer: try the engine yourself

`python -m gtfs_bench.explorer` opens a terminal app on top of the real engine. raptor-kmp
runs in a JVM with France loaded once, and you pick two stops or addresses anywhere in it:

- **Search:** type a few letters of a stop. Case and accents do not matter, and the commune
  counts too ("lyon gambetta"). A place is every stop sharing a name. Enter or a click
  picks it.
- **Addresses:** below the stops, an "Adresses · Photon" section lists addresses and named
  places ("20 rue de la Paix Paris", "Tour Eiffel"), found as Pelo finds them: the public
  [Photon](https://photon.komoot.io) geocoder, from 3 characters, once typing pauses, 6
  results, mainland France only, leaning towards the other end once it is chosen. The typed
  text goes to photon.komoot.io; answers are cached in `data/tmp/explorer/geocode.json`, and
  offline the section just stays empty. The engine gets the point itself
  (`Location.Point`, raptor-kmp's own address search) and walks to every stop within 500 m,
  at 4.8 km/h with a 1.3 detour factor, or the whole way when under 1 km. When that finds
  nothing, it searches again walking up to 6 km, as Pelo does, and says so. What it costs:
  `python -m gtfs_bench.engine --addresses` (results/address_queries.csv).
- **Date:** on the live network (`france-live`, the default once `gtfs_bench.refresh` has
  built it), any date from today to the end of its window. Each date runs on its day type:
  a weekday on the representative Tuesday's timetable, a Saturday on the Saturday's, a
  Sunday or public holiday on the Sunday's. Switching day type reloads the engine (about
  a second). The benchmark tiers (`--tier france-complete`…) have one day: the reference
  Tuesday, 24 November 2026.
- **Time:** a departure time, or "arriver avant" for arrive-by. Times past 24:00 reach the
  day's late-night trips (25:30 = 01:30 the next morning). The previous evening's trips
  running past midnight are not in the network, so very early mornings look emptier than
  they are.
- **Changes:** "correspondances max", 0 to 99 (− / + or type it, Enter). This is RAPTOR's
  round limit minus one; the engine's default is 4. High values make for absurd itineraries.
  Each extra round costs about 9.4 MB of search state on France, which is why the explorer
  starts the engine with `-Xmx2g`. Below that, a very high limit answers "pas assez de
  mémoire" and the engine keeps running.
- **School lines:** the "lignes scolaires" switch leaves every school line out of the
  search (raptor-kmp's `blockedRouteIds`) and searches again. It works on any network
  converted with its `school_routes.json` (`gtfs_bench.connected` writes one per variant);
  `--tier france-complete` also has the school-only networks.
- **Result:** the itinerary, leg by leg, with lines, stops and walks, and the alternatives
  raptor-kmp returns (fewer changes against earlier arrival). The time shown is the
  raptor-kmp call alone, measured inside the JVM.
- **Map:** France in braille, with every stop of the network as faint dots and the trip
  drawn over them. Ctrl+T switches between the zoom on the trip and the whole of France.
- **Shortcuts:** Ctrl+R for a random trip (two places 2 to 40 km apart), Ctrl+E to swap,
  Ctrl+G to compute.

```bash
python -m gtfs_bench.explorer                         # France
python -m gtfs_bench.explorer --tier metropole:lyon   # any converted tier
```

It needs the tier converted (the notebook) and `:benchmark-engine:installDist`.

- **Startup:** France takes about 8 s, which covers loading the network, indexing 170,000
  places, and a JIT warm-up of 30 queries. A checklist shows each step live, with a spinner,
  its time and what it found, under an overall bar; a failing step says why. Searches show
  a spinner too, with their time once past a quarter of a second.
- **First run:** naming the commune of each place takes a few more seconds, once, and is
  then cached in `data/tmp/explorer/`.
- **Coverage:** the France tier has no TGV or Intercités, so long trips across France
  find nothing or a chain of TER. `--tier france-connexe` has them (step 8).

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
