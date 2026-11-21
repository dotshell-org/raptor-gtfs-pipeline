# france-live, the Python build (archive)

This is how france-live was built before met-dataset-server: the daily job of the
whole-France benchmark, kept to rebuild a network by hand if ever needed. **Production is
met-dataset-server** (Kotlin, same rules, same bins), which builds france-live every night and
serves it at `https://api.dotshell.eu/france-live/epoch-2-3/`.

The benchmark itself (results, notebook, engine harness, tests, the old console) is in the git
tag `benchmark-final`.

## What it does

`python -m gtfs_bench.refresh`, for one day:

1. downloads every included feed of the catalogue's three layers (`regional`,
   `longue_distance`, `scolaire`) into `data/raw/` (conditional requests, last good zip kept);
2. computes the window and the day types (`horizon`): the window ends where a feed that
   matters stops; one representative Tuesday, Saturday and Sunday (and a holiday Tuesday);
3. normalizes each feed (`normalize`, DuckDB), merges them (`merge`: de-duplication, one route
   per stop pattern, homonym stops renamed by commune, walking transfers and station links),
   tags school lines (`school`);
4. converts the merged GTFS with this repository's CLI, one period per day type, into
   `data/raptor/france-live/{semaine,samedi,dimanche}/`.

It needs about 12 GB of RAM (the pipeline's conversion of France) and takes about 6 minutes.

## Run it

From this folder, Python 3.14 (Windows wheels), Java 21:

```powershell
..\..\gradlew.bat :cli:installDist          # from the repository root: the pipeline's CLI
py -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env                       # the Data Grand Lyon credentials, for TCL
.\refresh.ps1                                # = .venv\Scripts\python.exe -m gtfs_bench.refresh
```

| Option | Effect |
|---|---|
| `--force` | Rebuild even when no feed changed and the day types did not move |
| `--today 2026-11-21` | Build for another day |
| `--no-download` | Build from the zips already in `data/raw` (their `manifest.csv` too) |
| `--no-pan` | Skip the check for newer resources on transport.data.gouv.fr |
| `--no-build` | Download and report only |

TCL's feed needs a Data Grand Lyon account: `GRANDLYON_USER` and `GRANDLYON_PASSWORD` in
`.env`. If the portal refuses the script (HTTP 401), download `GTFS_TCL.ZIP` by hand into
`data/raw/tcl.zip` and run `python -m gtfs_bench.download --register tcl`.

Settings (transfer radii, the window's thresholds, the pipeline's heap…) have their defaults
in `gtfs_bench/settings.py`; a `settings.json` here overrides them.

## What is here

| Path | What |
|---|---|
| `gtfs_bench/refresh.py` | The daily job |
| `gtfs_bench/{catalog,credentials,download}.py` | The catalogue, credentials, downloads |
| `gtfs_bench/{horizon,normalize,merge,names,transfers,geo,school}.py` | Window and day types, normalization, merge |
| `gtfs_bench/convert.py` | The pipeline's CLI, with its peak memory |
| `gtfs_bench/settings.py` | Every setting and its default |
| `catalog/gtfs_france.csv` | The catalogue of French GTFS feeds (met-dataset-server has a copy) |
| `refresh.ps1`, `.env.example`, `requirements.txt` | Running it |
| `data/` | Git-ignored: `raw/`, `extracted/`, `normalized/`, `merged/`, `raptor/`, `logs/`, `results/` |

## Checked

On 2026-11-21, on the same 252 zips, this folder and the tag `benchmark-final` built the same
network: same window and day types (`horizon.json`), and in the merged GTFS identical stops,
trips, stop times and calendars, the same 96,255 routes and 1,292,390 of the same transfers.
The `.bin` files still differ, because the Python build is not deterministic from one run to
the next, whatever the code:

- DuckDB returns the merged routes in an order that varies between runs, and the route
  numbers in `routes.bin` follow that order;
- of walking transfers tied at the 30-neighbour cap (same time, equidistant stops), scipy's
  KD-tree keeps one or another (here 24 against 23 such pairs).

met-dataset-server builds the same network deterministically.
