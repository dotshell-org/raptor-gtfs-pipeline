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
| 1 | Feed catalogue | `catalog/` | |
| 2 | Download latest versions, credentials | `gtfs_bench/download.py` | |
| 3 | Merge N feeds into one per tier | `gtfs_bench/` + `tests/` | |
| 4 | Notebook running the whole chain | `notebooks/gtfs_france.ipynb` | |
| 5 | Pipeline conversion, measured | `gtfs_bench/convert.py` | |
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
