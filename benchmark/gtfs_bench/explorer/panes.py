"""The console's tabs besides the itinerary: catalogue, networks, actions, settings, results, help.

Each is a widget the Explorer app mounts in its TabbedContent. They read and write the same
files as the modules (catalog/gtfs_france.csv, settings.json, data/raptor, results/) and run
the same commands (tasks.py), so nothing done here differs from doing it by hand.
"""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import json
import os
import re
import shutil
import time
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, DataTable, Input, Label, MarkdownViewer, OptionList, RichLog, Select,
                             Static, Switch)
from textual.widgets.option_list import Option

from .. import settings as settings_module
from ..catalog import BENCHMARK_DIR, CATALOG_COLUMNS, CATALOG_CSV, read_catalog
from ..convert import DATA_DIR, RAPTOR_DIR, RESULTS_DIR
from . import tasks as task_module

BACKUP_DIR = DATA_DIR / "tmp" / "catalog-backups"
DOCS_DIR = BENCHMARK_DIR / "docs"
GUIDE_MD = DOCS_DIR / "GUIDE.md"
GUIDE_PDF = DOCS_DIR / "guide-console.pdf"
LAYERS = (("Toutes les couches", "*"), ("Régionale", "regional"), ("Longue distance", "longue_distance"),
          ("Scolaire", "scolaire"))
#: Catalogue fields the form edits, with their label; include, layer and clip have their own widgets.
EDITABLE = (("priority", "Priorité (la plus basse gagne un doublon)"), ("school", "Scolaire : all, ou regex sur le nom court"),
            ("keep_routes", "Garder seulement ces lignes (regex, nom court)"),
            ("keep_agencies", "Garder seulement ces agences (regex)"), ("drop_agencies", "Retirer ces agences (regex)"),
            ("keep_stop_ids", "Garder les courses dont tous les arrêts… (regex stop_id)"),
            ("drop_stop_ids", "Retirer les courses passant par… (regex stop_id)"),
            ("url", "URL de la dernière version"), ("notes", "Notes"))
REGEX_FIELDS = {"school", "keep_routes", "keep_agencies", "drop_agencies", "keep_stop_ids", "drop_stop_ids"}


def open_file(path: Path) -> bool:
    """Open a file with the system's own viewer (Windows); False when that is not possible."""
    if hasattr(os, "startfile") and path.exists():
        os.startfile(str(path))  # noqa: S606 (a file of this project, chosen in the console)
        return True
    return False


def thousands(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "–"


# ── catalogue ────────────────────────────────────────────────────────────────────────


def write_catalog(rows: list[dict], path: Path = CATALOG_CSV, backup_dir: Path = BACKUP_DIR) -> Path:
    """The catalogue back to CSV, the previous version kept in data/tmp/catalog-backups."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"gtfs_france-{dt.datetime.now():%Y%m%d-%H%M%S}.csv"
    if path.exists():
        shutil.copyfile(path, backup)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            for flag in ("include", "clip"):
                out[flag] = "true" if row.get(flag) is True or str(row.get(flag)).lower() == "true" else "false"
            writer.writerow(out)
    return backup


def check_row(row: dict) -> list[str]:
    """What is wrong with an edited row: a priority that is not a number, a regex that does not compile."""
    problems = []
    try:
        int(str(row.get("priority") or "50"))
    except ValueError:
        problems.append("la priorité doit être un nombre")
    for name in REGEX_FIELDS:
        value = (row.get(name) or "").strip()
        if value and value != "all":
            try:
                re.compile(value)
            except re.error as error:
                problems.append(f"{name} : regex invalide ({error})")
    return problems


class CataloguePane(Vertical):
    DEFAULT_CSS = """
    CataloguePane #cat-filters { height: 3; }
    CataloguePane #cat-search { width: 1fr; }
    CataloguePane #cat-layer, CataloguePane #cat-included { width: 26; }
    CataloguePane #cat-count { width: 30; padding: 1 1; color: $text-muted; }
    CataloguePane #cat-table { width: 1fr; }
    CataloguePane #cat-form { width: 58; padding: 0 1; border-left: solid $panel-lighten-2; }
    CataloguePane .field-label { margin-top: 1; color: $text-muted; }
    CataloguePane #cat-buttons { height: 3; margin-top: 1; }
    CataloguePane #cat-buttons Button { margin-right: 1; }
    CataloguePane .switch-row { height: 3; }
    CataloguePane .switch-row Label { padding: 1 1; }
    """

    def __init__(self, catalog_path: Path = CATALOG_CSV, manifest_loader=None, **kwargs):
        super().__init__(**kwargs)
        self.catalog_path, self.manifest_loader = catalog_path, manifest_loader
        self.rows: list[dict] = []
        self.manifest: dict = {}
        self.current: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="cat-filters"):
            yield Input(placeholder="Chercher : identifiant, nom, région, notes…", id="cat-search")
            yield Select(LAYERS, value="*", allow_blank=False, id="cat-layer")
            yield Select((("Inclus et exclus", "*"), ("Inclus", "true"), ("Exclus", "false")), value="*",
                         allow_blank=False, id="cat-included")
            yield Static("", id="cat-count")
        with Horizontal():
            yield DataTable(id="cat-table", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="cat-form"):
                yield Static("Choisis un flux dans la liste.", id="cat-title")
                yield Static("", id="cat-facts")
                with Horizontal(classes="switch-row"):
                    yield Switch(id="cat-include")
                    yield Label("inclus dans les réseaux")
                with Horizontal(classes="switch-row"):
                    yield Switch(id="cat-clip")
                    yield Label("découpé à la zone du palier (flux nationaux)")
                yield Label("Couche", classes="field-label")
                yield Select(LAYERS[1:], value="regional", allow_blank=False, id="cat-layer-edit")
                for name, label in EDITABLE:
                    yield Label(label, classes="field-label")
                    yield Input(id=f"cat-{name}")
                with Horizontal(id="cat-buttons"):
                    yield Button("Enregistrer", id="cat-save", variant="primary")
                    yield Button("Télécharger ce flux", id="cat-download")
                    yield Button("Annuler", id="cat-revert")
                yield Static("", id="cat-message")

    def on_mount(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        for label, width in (("flux", 24), ("inclus", 6), ("couche", 10), ("région", 14), ("niveau", 11),
                             ("nom", 30), ("scolaire", 8), ("fin des données", 15), ("statut", 12)):
            table.add_column(label, width=width)
        self.reload()

    def reload(self) -> None:
        self.rows = read_catalog(self.catalog_path)
        if self.manifest_loader is not None:
            self.manifest = self.manifest_loader()
        else:
            from ..download import read_manifest
            try:
                self.manifest = read_manifest()
            except OSError:
                self.manifest = {}
        self.fill()

    def visible(self) -> list[dict]:
        text = self.query_one("#cat-search", Input).value.strip().lower()
        layer = self.query_one("#cat-layer", Select).value
        included = self.query_one("#cat-included", Select).value
        shown = []
        for row in self.rows:
            if layer != "*" and row.get("layer") != layer:
                continue
            if included != "*" and str(bool(row.get("include"))).lower() != included:
                continue
            if text and not any(text in str(row.get(k, "")).lower()
                                for k in ("feed_id", "name", "region_name", "notes", "metropole")):
                continue
            shown.append(row)
        return shown

    def fill(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.clear()
        shown = self.visible()
        for row in shown:
            entry = self.manifest.get(row["feed_id"])
            table.add_row(row["feed_id"][:24], "✓" if row.get("include") else "·", row.get("layer", "")[:10],
                          row.get("region_name", "")[:14], row.get("level", "")[:11], row.get("name", "")[:30],
                          row.get("school", "")[:8], getattr(entry, "service_end", "") or "",
                          getattr(entry, "status", "") or "", key=row["feed_id"])
        self.query_one("#cat-count", Static).update(f"{len(shown)} / {len(self.rows)} flux · "
                                                    f"{sum(1 for r in self.rows if r.get('include'))} inclus")

    @on(Input.Changed, "#cat-search")
    @on(Select.Changed, "#cat-layer, #cat-included")
    def filters_changed(self) -> None:
        if self.rows:
            self.fill()

    @on(DataTable.RowHighlighted, "#cat-table")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value:
            self.show(event.row_key.value)

    def row(self, feed_id: str) -> dict:
        return next(r for r in self.rows if r["feed_id"] == feed_id)

    def show(self, feed_id: str) -> None:
        self.current = feed_id
        row = self.row(feed_id)
        entry = self.manifest.get(feed_id)
        self.query_one("#cat-title", Static).update(Text(f"{feed_id}\n{row.get('name', '')}", style="bold"))
        facts = Text()
        facts.append(f"{row.get('region_name', '')} · {row.get('level', '')} · {row.get('modes', '')}\n", style="dim")
        if entry is not None:
            size = f"{(entry.size or 0) / 1024**2:.1f} Mo" if entry.size else "–"
            facts.append(f"Téléchargé : {entry.status} · {size} · {str(entry.downloaded_at)[:16]}\n")
            facts.append(f"Données : {entry.service_start or '?'} → {entry.service_end or '?'}\n")
            if entry.error:
                facts.append(f"Erreur : {entry.error}\n", style="#e34948")
        else:
            facts.append("Jamais téléchargé.\n", style="dim")
        if row.get("pan_dataset_id"):
            facts.append(f"PAN : transport.data.gouv.fr/datasets/{row['pan_dataset_id']}\n", style="dim")
        self.query_one("#cat-facts", Static).update(facts)
        self.query_one("#cat-include", Switch).value = bool(row.get("include"))
        self.query_one("#cat-clip", Switch).value = bool(row.get("clip"))
        self.query_one("#cat-layer-edit", Select).value = row.get("layer") or "regional"
        for name, _ in EDITABLE:
            self.query_one(f"#cat-{name}", Input).value = str(row.get(name) or "")
        self.query_one("#cat-message", Static).update("")

    def edited(self) -> dict:
        row = dict(self.row(self.current))
        row["include"] = self.query_one("#cat-include", Switch).value
        row["clip"] = self.query_one("#cat-clip", Switch).value
        row["layer"] = self.query_one("#cat-layer-edit", Select).value
        for name, _ in EDITABLE:
            row[name] = self.query_one(f"#cat-{name}", Input).value.strip()
        return row

    @on(Button.Pressed, "#cat-save")
    def save(self) -> None:
        if not self.current:
            return
        row = self.edited()
        message = self.query_one("#cat-message", Static)
        problems = check_row(row)
        if problems:
            message.update(Text("Pas enregistré : " + " ; ".join(problems), style="#e34948"))
            return
        self.rows = [row if r["feed_id"] == self.current else r for r in self.rows]
        backup = write_catalog(self.rows, self.catalog_path)
        message.update(Text(f"Enregistré. Version précédente : {backup.name}. Les réseaux changent à leur "
                            f"prochaine construction (Actions).", style="#1baf7a"))
        self.fill()

    @on(Button.Pressed, "#cat-revert")
    def revert(self) -> None:
        if self.current:
            self.show(self.current)

    @on(Button.Pressed, "#cat-download")
    def download(self) -> None:
        if self.current:
            self.app.run_task("download", f"--feeds {self.current}")


# ── networks ─────────────────────────────────────────────────────────────────────────


def scan_networks(raptor_dir: Path = RAPTOR_DIR) -> list[dict]:
    """Every converted network: tiers (<name>/bench) and live ones (<name>/<day type>)."""
    found = []
    if not raptor_dir.exists():
        return found
    for folder in sorted(p for p in raptor_dir.iterdir() if p.is_dir() and not p.name.endswith((".new", ".old"))):
        dataset_path = folder / "dataset.json"
        try:
            dataset = json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.exists() else {}
        except ValueError:
            dataset = {}
        periods = {p.get("name"): p.get("stats", {}) for p in dataset.get("periods", [])}
        if (folder / "horizon.json").exists():
            data_dir, kind, main = folder, "à jour", "semaine"
            horizon = json.loads((folder / "horizon.json").read_text(encoding="utf-8"))
            note = f"{horizon.get('start')} → {horizon.get('end')} · {', '.join(periods) or '?'}"
        elif (folder / "bench" / "routes.bin").exists():
            data_dir, kind, main, note = folder / "bench", "un jour", "bench", ""
        else:
            continue
        bins = [p for p in data_dir.rglob("*.bin")]
        school_file = next(iter(data_dir.rglob("school_routes.json")), None)
        school = json.loads(school_file.read_text(encoding="utf-8")).get("lines") if school_file else None
        stats = periods.get(main, {})
        found.append({"key": folder.name, "dir": data_dir, "kind": kind, "stops": stats.get("stops"),
                      "routes": stats.get("routes"), "trips": stats.get("trips"),
                      "bins_mb": round(sum(p.stat().st_size for p in bins) / 1024**2, 1), "school": school,
                      "built": dt.datetime.fromtimestamp(max(p.stat().st_mtime for p in bins)).strftime("%d/%m %H:%M") if bins else "",
                      "note": note, "periods": list(periods)})
    return found


class NetworksPane(Vertical):
    DEFAULT_CSS = """
    NetworksPane #net-table { height: 1fr; }
    NetworksPane #net-bar { height: 3; }
    NetworksPane #net-bar Button { margin-right: 1; }
    NetworksPane #net-detail { height: auto; min-height: 4; padding: 1 1; background: $boost; }
    """

    def __init__(self, raptor_dir: Path = RAPTOR_DIR, **kwargs):
        super().__init__(**kwargs)
        self.raptor_dir = raptor_dir
        self.networks: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("Les réseaux convertis sur cette machine. « À jour » : le réseau glissant de la mise à jour "
                     "quotidienne, un réseau par jour type ; « un jour » : un palier du benchmark, le mardi de "
                     "référence.", id="net-intro")
        yield DataTable(id="net-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="net-bar"):
            yield Button("Ouvrir dans l'itinéraire", id="net-open", variant="primary")
            yield Button("Actualiser la liste", id="net-refresh")
        yield Static("", id="net-detail")

    def on_mount(self) -> None:
        self.query_one("#net-table", DataTable).add_columns(
            "réseau", "type", "arrêts", "lignes", "courses", ".bin", "lignes scolaires", "construit le", "fenêtre / jours types")
        self.reload()

    @on(Button.Pressed, "#net-refresh")
    def reload(self) -> None:
        self.networks = scan_networks(self.raptor_dir)
        table = self.query_one("#net-table", DataTable)
        table.clear()
        for n in self.networks:
            table.add_row(n["key"], n["kind"], thousands(n["stops"]), thousands(n["routes"]), thousands(n["trips"]),
                          f"{n['bins_mb']} Mo", thousands(n["school"]) if n["school"] else "–", n["built"], n["note"],
                          key=n["key"])

    def selected(self) -> dict | None:
        table = self.query_one("#net-table", DataTable)
        if not self.networks or table.cursor_row is None:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next((n for n in self.networks if n["key"] == key), None)

    @on(DataTable.RowHighlighted, "#net-table")
    def highlighted(self) -> None:
        n = self.selected()
        if n:
            text = Text(f"{n['key']}  ", style="bold")
            shown = n["dir"].relative_to(BENCHMARK_DIR) if n["dir"].is_relative_to(BENCHMARK_DIR) else Path(n["dir"].name)
            text.append(f"{shown.as_posix()}\n", style="dim")
            if n["kind"] == "à jour":
                text.append(f"Fenêtre {n['note']}. Chaque date choisie dans l'itinéraire prend son jour type.")
            else:
                text.append("Horaires du jour de référence.")
            self.query_one("#net-detail", Static).update(text)

    @on(Button.Pressed, "#net-open")
    def open_selected(self) -> None:
        n = self.selected()
        if n:
            self.app.open_network(n["key"])


# ── actions ──────────────────────────────────────────────────────────────────────────


class ActionsPane(Horizontal):
    DEFAULT_CSS = """
    ActionsPane #act-list { width: 44; border-right: solid $panel-lighten-2; }
    ActionsPane #act-main { padding: 0 1; }
    ActionsPane #act-title { text-style: bold; margin-top: 1; }
    ActionsPane #act-what { margin: 1 0; }
    ActionsPane #act-bar { height: 3; }
    ActionsPane #act-bar Button { margin-right: 1; }
    ActionsPane #act-options { width: 1fr; }
    ActionsPane #act-status { height: 2; padding: 0 1; background: $boost; }
    ActionsPane #act-log { height: 1fr; border: round $panel-lighten-2; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected = task_module.TASKS[0]
        self.process: asyncio.subprocess.Process | None = None
        self.started = 0.0
        self.running: task_module.Task | None = None

    def compose(self) -> ComposeResult:
        options, group = [], None
        for t in task_module.TASKS:
            if t.group != group:
                group = t.group
                options.append(Option(Text(group.upper(), style="bold dim"), disabled=True))
            options.append(Option(f"  {t.title}", id=t.key))
        yield OptionList(*options, id="act-list")
        with Vertical(id="act-main"):
            yield Static("", id="act-title")
            yield Static("", id="act-what")
            yield Label("Options (modifiables avant de lancer)")
            with Horizontal(id="act-bar"):
                yield Input(id="act-options")
                yield Button("Lancer", id="act-run", variant="primary")
                yield Button("Arrêter", id="act-stop", variant="error", disabled=True)
                yield Button("Effacer", id="act-clear")
            yield Static("Rien en cours.", id="act-status")
            yield RichLog(id="act-log", wrap=True, markup=False, highlight=False, max_lines=5000)

    def on_mount(self) -> None:
        self.select(self.selected.key)
        self.set_interval(1.0, self.tick)

    def default_options(self, t: task_module.Task) -> str:
        if t.key == "schedule":
            return task_module.schedule_command(settings_module.load().live.refresh_time)
        return t.options

    def select(self, key: str, options: str | None = None) -> None:
        self.selected = task_module.task(key)
        t = self.selected
        self.query_one("#act-title", Static).update(t.title)
        what = Text(t.what + "\n")
        what.append(f"Durée : {t.duration}." if t.duration else "", style="dim")
        if t.heavy:
            what.append("  Gourmand en mémoire (jusqu'à ~10 Go) : ferme ce qui peut l'être.", style="#eda100")
        self.query_one("#act-what", Static).update(what)
        self.query_one("#act-options", Input).value = options if options is not None else self.default_options(t)
        listing = self.query_one("#act-list", OptionList)
        for i in range(listing.option_count):
            if listing.get_option_at_index(i).id == key:
                listing.highlighted = i

    @on(OptionList.OptionHighlighted, "#act-list")
    def highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id and event.option.id != self.selected.key:
            self.select(event.option.id)

    @on(Button.Pressed, "#act-run")
    def run_selected(self) -> None:
        self.start(self.selected, self.query_one("#act-options", Input).value)

    @on(Button.Pressed, "#act-clear")
    def clear(self) -> None:
        self.query_one("#act-log", RichLog).clear()

    @on(Button.Pressed, "#act-stop")
    def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.kill()
            self.query_one("#act-log", RichLog).write(Text("— arrêté à la demande —", style="#eda100"))

    def start(self, t: task_module.Task, options: str) -> bool:
        if self.running is not None:
            self.query_one("#act-log", RichLog).write(Text(f"« {self.running.title} » tourne encore : attends ou arrête-la.",
                                                           style="#eda100"))
            return False
        command = t.command(options)
        log = self.query_one("#act-log", RichLog)
        log.write(Text(f"\n▶ {t.title}  ({dt.datetime.now():%H:%M:%S})", style="bold #2a78d6"))
        log.write(Text(task_module.describe(command), style="dim"))
        self.running, self.started = t, time.perf_counter()
        self.query_one("#act-run", Button).disabled = True
        self.query_one("#act-stop", Button).disabled = False
        self.execute(t, command)
        return True

    def tick(self) -> None:
        status = self.query_one("#act-status", Static)
        if self.running is not None:
            elapsed = int(time.perf_counter() - self.started)
            status.update(Text(f"⏳ {self.running.title} · {elapsed // 60} min {elapsed % 60:02d} s", style="bold"))

    @work(exclusive=True, group="task")
    async def execute(self, t: task_module.Task, command: list[str]) -> None:
        log = self.query_one("#act-log", RichLog)
        code = None
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=str(BENCHMARK_DIR), env=task_module.environment(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            assert self.process.stdout is not None
            while True:
                raw = await self.process.stdout.readline()
                if not raw:
                    break
                for line in raw.decode("utf-8", errors="replace").replace("\r", "\n").splitlines():
                    if line.strip():
                        log.write(line)
            code = await self.process.wait()
        except (OSError, ValueError) as error:
            log.write(Text(f"Impossible de lancer : {error}", style="#e34948"))
        elapsed = int(time.perf_counter() - self.started)
        done = code == 0
        verdict = Text(f"{'✓' if done else '✗'} {t.title} : {'terminé' if done else f'échec (code {code})'} "
                       f"en {elapsed // 60} min {elapsed % 60:02d} s", style="bold #1baf7a" if done else "bold #e34948")
        log.write(verdict)
        self.query_one("#act-status", Static).update(verdict)
        self.running, self.process = None, None
        self.query_one("#act-run", Button).disabled = False
        self.query_one("#act-stop", Button).disabled = True
        if done:
            self.app.task_finished(t.key)


# ── settings ─────────────────────────────────────────────────────────────────────────


class SettingsPane(VerticalScroll):
    DEFAULT_CSS = """
    SettingsPane { padding: 0 2; }
    SettingsPane .group { text-style: bold; color: $accent; margin-top: 1; }
    SettingsPane .setting { height: 3; }
    SettingsPane .setting Label { width: 46; padding: 1 1 0 0; }
    SettingsPane .setting Input { width: 24; }
    SettingsPane .setting Switch { width: 24; }
    SettingsPane .help { padding: 1 0 0 2; color: $text-muted; width: 1fr; }
    SettingsPane #set-bar { height: 3; margin-top: 1; }
    SettingsPane #set-bar Button { margin-right: 1; }
    """

    def __init__(self, path: Path = settings_module.SETTINGS_FILE, **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def compose(self) -> ComposeResult:
        yield Static(f"Réglages de toute la chaîne, enregistrés dans {self.path.name} (cette machine seulement). "
                     "Ils servent aux actions lancées ensuite, au notebook et au prochain démarrage du moteur.",
                     id="set-intro")
        current = settings_module.load(self.path)
        group = None
        for key, label, name, title, help_text, kind, value in settings_module.fields_of(current):
            if key != group:
                group = key
                yield Static(label, classes="group")
            with Horizontal(classes="setting"):
                yield Label(title)
                if kind is bool:
                    yield Switch(value=bool(value), id=f"set-{key}-{name}")
                else:
                    yield Input(value=str(value), id=f"set-{key}-{name}")
                yield Static(help_text, classes="help")
        with Horizontal(id="set-bar"):
            yield Button("Enregistrer", id="set-save", variant="primary")
            yield Button("Revenir aux valeurs par défaut", id="set-defaults")
        yield Static("", id="set-message")

    def values(self) -> tuple[settings_module.Settings, list[str]]:
        result, problems = settings_module.Settings(), []
        for key, _, name, title, _, kind, _ in settings_module.fields_of(result):
            widget = self.query_one(f"#set-{key}-{name}")
            try:
                value = widget.value if kind is bool else settings_module.parse(kind, widget.value)
            except ValueError as error:
                problems.append(f"{title} : {error}")
                continue
            setattr(getattr(result, key), name, value)
        return result, problems

    @on(Button.Pressed, "#set-save")
    def save(self) -> None:
        values, problems = self.values()
        message = self.query_one("#set-message", Static)
        if problems:
            message.update(Text("Pas enregistré : " + " ; ".join(problems), style="#e34948"))
            return
        settings_module.save(values, self.path)
        message.update(Text(f"Enregistré dans {self.path.name}.", style="#1baf7a"))
        self.app.settings_changed(values)

    @on(Button.Pressed, "#set-defaults")
    def defaults(self) -> None:
        defaults = settings_module.Settings()
        for key, _, name, _, _, kind, value in settings_module.fields_of(defaults):
            widget = self.query_one(f"#set-{key}-{name}")
            widget.value = bool(value) if kind is bool else str(value)
        self.query_one("#set-message", Static).update("Valeurs par défaut affichées : « Enregistrer » pour les garder.")


# ── results ──────────────────────────────────────────────────────────────────────────


def result_files(results_dir: Path = RESULTS_DIR) -> list[Path]:
    reports = [BENCHMARK_DIR / n for n in ("RESULTS.fr.md", "RESULTS.md", "README.md")]
    files = sorted(p for p in results_dir.glob("*") if p.suffix in (".csv", ".png", ".json", ".md"))
    return [p for p in reports if p.exists()] + files


class ResultsPane(Horizontal):
    DEFAULT_CSS = """
    ResultsPane #res-list { width: 38; border-right: solid $panel-lighten-2; }
    ResultsPane #res-main { padding: 0 1; }
    ResultsPane #res-bar { height: 3; }
    ResultsPane #res-table { height: 1fr; }
    ResultsPane #res-md { height: 1fr; }
    ResultsPane #res-info { height: auto; padding: 1 1; }
    """

    def __init__(self, results_dir: Path = RESULTS_DIR, **kwargs):
        super().__init__(**kwargs)
        self.results_dir = results_dir
        self.files: list[Path] = []
        self.current: Path | None = None

    def compose(self) -> ComposeResult:
        yield OptionList(id="res-list")
        with Vertical(id="res-main"):
            with Horizontal(id="res-bar"):
                yield Button("Ouvrir avec Windows", id="res-open")
                yield Static("", id="res-info")
            yield DataTable(id="res-table", zebra_stripes=True)
            yield MarkdownViewer("", id="res-md", show_table_of_contents=True)

    def on_mount(self) -> None:
        self.files = result_files(self.results_dir)
        self.query_one("#res-list", OptionList).add_options([Option(p.name, id=str(i)) for i, p in enumerate(self.files)])
        self.query_one("#res-table").display = False
        if self.files:
            self.show(self.files[0])

    @on(OptionList.OptionHighlighted, "#res-list")
    def picked(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is not None:
            self.show(self.files[int(event.option.id)])

    def show(self, path: Path) -> None:
        self.current = path
        table, md, info = self.query_one("#res-table", DataTable), self.query_one("#res-md", MarkdownViewer), self.query_one("#res-info", Static)
        info.update(f"{path.name} · {path.stat().st_size / 1024:.0f} Ko")
        if path.suffix == ".csv":
            table.display, md.display = True, False
            table.clear(columns=True)
            with path.open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            if rows:
                table.add_columns(*rows[0])
                for row in rows[1:1001]:
                    table.add_row(*(row + [""] * (len(rows[0]) - len(row)))[:len(rows[0])])
                info.update(f"{path.name} · {len(rows) - 1} lignes" + (" (1 000 premières affichées)" if len(rows) > 1001 else ""))
        elif path.suffix in (".md", ".json"):
            table.display, md.display = False, True
            text = path.read_text(encoding="utf-8")
            md.document.update(text if path.suffix == ".md" else f"```json\n{text[:20000]}\n```")
        else:
            table.display, md.display = False, True
            md.document.update(f"# {path.name}\n\nUne image : « Ouvrir avec Windows » l'affiche dans la visionneuse.")

    @on(Button.Pressed, "#res-open")
    def open_current(self) -> None:
        if self.current and not open_file(self.current):
            self.query_one("#res-info", Static).update("Impossible d'ouvrir ce fichier ici.")


# ── help ─────────────────────────────────────────────────────────────────────────────


class HelpPane(Vertical):
    DEFAULT_CSS = """
    HelpPane #help-bar { height: 3; }
    HelpPane #help-md { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="help-bar"):
            yield Button("Ouvrir le guide PDF", id="help-pdf", variant="primary")
            yield Static("  Le même guide, avec les captures d'écran : docs/guide-console.pdf", id="help-info")
        source = GUIDE_MD if GUIDE_MD.exists() else BENCHMARK_DIR / "README.md"
        yield MarkdownViewer(source.read_text(encoding="utf-8"), id="help-md", show_table_of_contents=True)

    @on(Button.Pressed, "#help-pdf")
    def open_pdf(self) -> None:
        if not open_file(GUIDE_PDF):
            self.query_one("#help-info", Static).update("  Pas encore de PDF : Actions → Régénérer le guide PDF.")
