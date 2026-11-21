# The france-live console

A terminal app (Textual) that shows france-live as the apps get it:

- it installs and updates france-live from the official delivery
  (`https://api.dotshell.eu/france-live/epoch-2-3/`) with **dataset-sync**, the apps' library,
  and shows each update: delta or full pack, where every byte came from, what it cost;
- it routes on the installed version with **raptor-kmp**, the apps' engine: stops and
  addresses anywhere in France, any date of the version's window, with a braille map;
- it shows the version's window, day types, sources and licence (ODbL 1.0).

Nothing here builds a network: met-dataset-server does, every night. The user guide, in
French, is [docs/GUIDE.md](docs/GUIDE.md), also as a PDF with screenshots
([docs/guide-console.pdf](docs/guide-console.pdf)).

## Run it

Windows, from this folder:

```powershell
.\console.ps1
```

The first run makes `.venv` from `requirements.txt` and builds the engine; later runs start
the console directly. It needs Python 3.12+, Java 21+ and a terminal of at least 160 × 45.

By hand:

```powershell
cd engine; ..\..\gradlew.bat installDist; cd ..
py -m venv .venv; .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe -m met_console [--data <dir>] [--xmx 1g] [--java <java>]
```

## Layout

| Path | What |
|---|---|
| `met_console/` | The console: `app.py` (itinerary), `updates.py` (Mise à jour), `panes.py` (data, settings, help), `backend.py` and `sync.py` (the two JVM children), `daytypes.py`, `geo.py`, `places.py`, `geocode.py`, `mapview.py`, `guide.py` |
| `engine/` | Its own Gradle build (Kotlin 2.3): `ServeKt` keeps one day type loaded in raptor-kmp and answers JSON lines; `SyncKt` runs dataset-sync and reports each step as JSON lines |
| `data/` | Per machine, git-ignored: `france-live/` (dataset-sync's root: `installed.json` and the version), `cache/`, `settings.json`, `history.json` |
| `docs/` | `GUIDE.md`, its screenshots (`img/`) and the PDF |
| `tests/` | `pytest` (from this folder: `.venv\Scripts\python.exe -m pytest`) |

The engine depends on `eu.dotshell:raptor-kmp-jvm` and `eu.dotshell.met:dataset-sync-jvm`,
taken from `~/.m2` before Maven Central: until dataset-sync (and a raptor-kmp release) are on
Central, publish them locally (`./gradlew :dataset-sync:publishToMavenLocal` in
met-dataset-server).

## Tests

- `.venv\Scripts\python.exe -m pytest`: the console with a fake engine and replayed SyncKt
  lines; the real engine too when `data/` holds an installed version.
- `CONSOLE_LIVE_TEST=1` adds a real installation from api.dotshell.eu into a temporary folder
  (about 45 MB).
- `cd engine; ..\..\gradlew.bat test`: SyncKt against a local HTTP server, with packs built
  by met-dataset-server (`src/test/resources/sync/make.ps1` rebuilds them).

## The guide

```powershell
.venv\Scripts\python.exe -m met_console.guide [--no-shots] [--no-update] [--no-pdf]
```

It runs the real console headless on the installed version, saves a screenshot of each tab
in `docs/img/`, installs the latest version into a temporary folder for the Mise à jour
screenshots (a real download), then prints `docs/GUIDE.md` to `docs/guide-console.pdf` with
Microsoft Edge.
