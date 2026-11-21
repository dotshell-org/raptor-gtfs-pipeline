"""The console's tabs besides the itinerary and the updates (updates.py): data, settings, help.

Each is a widget the Explorer app mounts in its TabbedContent.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Label, MarkdownViewer, Static, Switch

from . import settings as settings_module
from .daytypes import LABELS
from .dataset import Installed, megabytes
from .paths import CONSOLE_DIR, DOCS_DIR

GUIDE_MD = DOCS_DIR / "GUIDE.md"
GUIDE_PDF = DOCS_DIR / "guide-console.pdf"
GREEN, RED, ORANGE, BLUE = "#1baf7a", "#e34948", "#eda100", "#2a78d6"


def thousands(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "–"


def open_file(path: Path) -> bool:
    """Open a file with the system's own viewer (Windows); False when that is not possible."""
    if hasattr(os, "startfile") and path.exists():
        os.startfile(str(path))  # noqa: S606 (a file of this project, chosen in the console)
        return True
    return False


def local_time(moment: dt.datetime | None) -> str:
    return moment.astimezone().strftime("%d/%m/%Y %H:%M") if moment else "?"


# ── data ─────────────────────────────────────────────────────────────────────────────


class DataPane(Horizontal):
    """The installed version: what it covers, where it comes from, under which licence."""

    DEFAULT_CSS = """
    DataPane #data-left { width: 70; padding: 0 1; border-right: solid $panel-lighten-2; }
    DataPane .data-title { text-style: bold; color: $accent; margin-top: 1; }
    DataPane #data-right { padding: 0 1; }
    DataPane #src-search { margin-top: 1; }
    DataPane #src-table { height: 1fr; }
    DataPane #src-count { height: 1; color: $text-muted; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sources: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="data-left"):
            yield Static("Version", classes="data-title")
            yield Static("", id="data-version")
            yield Static("Fenêtre et jours types", classes="data-title")
            yield Static("", id="data-days")
            yield Static("Moteur", classes="data-title")
            yield Static("", id="data-engine")
            yield Static("Licence", classes="data-title")
            yield Static("", id="data-licence")
        with Vertical(id="data-right"):
            yield Static("Sources", classes="data-title")
            yield Input(placeholder="Chercher un flux : identifiant, nom, licence…", id="src-search")
            yield Static("", id="src-count")
            yield DataTable(id="src-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#src-table", DataTable)
        for label, width in (("flux", 22), ("nom", 32), ("couche", 15), ("licence", 16), ("courses", 8)):
            table.add_column(label, width=width)
        self.show(self.app.installed)

    def show(self, installed: Installed | None) -> None:
        if installed is None:
            for widget in ("#data-version", "#data-days", "#data-licence"):
                self.query_one(widget, Static).update(Text("Aucune version installée : F2 Mise à jour.", style="dim"))
            self.sources = []
            self.fill()
            return
        dataset = installed.read("dataset.json") or {}
        validity = dataset.get("validity") or {}
        version = Text()
        version.append(f"{installed.version}\n", style=f"bold {GREEN}")
        version.append(f"publiée le {local_time(installed.created_at())} · {megabytes(installed.size())} sur le disque\n")
        version.append(f"valable du {validity.get('start_date', '?')} au {validity.get('end_date', '?')}\n", style="dim")
        version.append(f"{dataset.get('tool_version', '')} · format {installed.latest.get('epoch', '?')}\n", style="dim")
        shown = installed.dir.relative_to(CONSOLE_DIR) if installed.dir.is_relative_to(CONSOLE_DIR) else installed.dir
        version.append(shown.as_posix(), style="dim")
        self.query_one("#data-version", Static).update(version)
        self.query_one("#data-days", Static).update(self.days(installed, dataset))
        self.query_one("#data-licence", Static).update(self.licence(installed.read("licence.json")))
        self.sources = installed.read("sources.json") or []
        self.fill()

    @staticmethod
    def days(installed: Installed, dataset: dict) -> Table | Text:
        plan = installed.plan()
        stats = {p.get("name"): p.get("stats", {}) for p in dataset.get("periods", [])}
        table = Table(box=None, padding=(0, 1), show_edge=False)
        for label, justify in (("jour type", "left"), ("modèle", "left"), ("arrêts", "right"), ("lignes", "right"),
                               ("courses", "right"), ("taille", "right")):
            table.add_column(label, justify=justify, style="bold" if label == "jour type" else None)
        for name in installed.day_types():
            s = stats.get(name, {})
            table.add_row(LABELS.get(name, name), (plan.days.get(name, "?") if plan else "?"), thousands(s.get("stops")),
                          thousands(s.get("routes")), thousands(s.get("trips")), megabytes(installed.size(name)))
        if plan is None:
            return table
        intro = Text()
        intro.append(f"Du {plan.start} au {plan.end}", style="bold")
        intro.append(f" : {plan.feeds} flux roulent la première semaine.\n", style="dim")
        if plan.binding_feed:
            intro.append(f"La fenêtre s'arrête avec {plan.binding_feed} ({plan.binding_share * 100:.1f} % des courses).\n",
                         style="dim")
        if plan.lost:
            intro.append(f"{len(plan.lost)} petits flux s'arrêtent avant : "
                         + ", ".join(f"{l['feed_id']} ({l['last_day'][5:]})" for l in plan.lost[:8]) + "\n", style="dim")
        intro.append("Chaque date de la fenêtre roule sur le jour type du même genre (fêtes = dimanche).\n", style="dim")
        from rich.console import Group
        return Group(intro, table)

    @staticmethod
    def licence(licence: dict | None) -> Text:
        if not licence:
            return Text("Pas de licence.json dans cette version.", style="dim")
        text = Text()
        text.append(f"{licence.get('name', licence.get('licence'))}\n", style="bold")
        text.append(f"{licence.get('url', '')}\n", style="underline")
        text.append(licence.get("notice", ""), style="dim")
        return text

    def show_engine(self, info: dict | None) -> None:
        if not info:
            self.query_one("#data-engine", Static).update(Text("Pas démarré.", style="dim"))
            return
        text = Text()
        text.append(f"raptor-kmp {info.get('engine', '?')}", style="bold")
        text.append(f" · Java {info.get('java', '?')}\n")
        text.append(f"jour type chargé : {info.get('period', '?')} · {thousands(info.get('stops'))} arrêts · "
                    f"{thousands(info.get('routes'))} lignes · {thousands(info.get('trips'))} courses\n", style="dim")
        text.append(f"chargé en {info.get('loadMs', 0):.0f} ms · {info.get('heapMb', 0):.0f} Mo de tas · "
                    f"{thousands(info.get('schoolRoutes'))} lignes scolaires", style="dim")
        self.query_one("#data-engine", Static).update(text)

    def visible(self) -> list[dict]:
        query = self.query_one("#src-search", Input).value.strip().lower()
        if not query:
            return self.sources
        return [s for s in self.sources if any(query in str(s.get(k, "")).lower()
                                               for k in ("feed_id", "name", "layer", "licence"))]

    @on(Input.Changed, "#src-search")
    def fill(self) -> None:
        table = self.query_one("#src-table", DataTable)
        table.clear()
        shown = self.visible()
        for s in shown:
            table.add_row(str(s.get("feed_id", ""))[:22], str(s.get("name", ""))[:32], str(s.get("layer", ""))[:15],
                          str(s.get("licence", ""))[:16], thousands(s.get("trips")))
        licences: dict[str, int] = {}
        for s in self.sources:
            licences[s.get("licence") or "?"] = licences.get(s.get("licence") or "?", 0) + 1
        summary = " · ".join(f"{n} {k}" for k, n in sorted(licences.items(), key=lambda kv: -kv[1]))
        self.query_one("#src-count", Static).update(f"{len(shown)} / {len(self.sources)} flux  ·  {summary}")


# ── settings ─────────────────────────────────────────────────────────────────────────


class SettingsPane(VerticalScroll):
    DEFAULT_CSS = """
    SettingsPane { padding: 0 2; }
    SettingsPane .group { text-style: bold; color: $accent; margin-top: 1; }
    SettingsPane .setting { height: 3; }
    SettingsPane .setting Label { width: 40; padding: 1 1 0 0; }
    SettingsPane .setting Input { width: 34; }
    SettingsPane .setting Switch { width: 34; }
    SettingsPane .help { padding: 1 0 0 2; color: $text-muted; width: 1fr; }
    SettingsPane #set-bar { height: 3; margin-top: 1; }
    SettingsPane #set-bar Button { margin-right: 1; }
    """

    def __init__(self, path: Path, **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def compose(self) -> ComposeResult:
        shown = self.path.relative_to(CONSOLE_DIR) if self.path.is_relative_to(CONSOLE_DIR) else self.path
        yield Static(f"Réglages de la console, enregistrés dans {shown.as_posix()} (cette machine seulement).",
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
        return result, problems + settings_module.check(result)

    @on(Button.Pressed, "#set-save")
    def save(self) -> None:
        values, problems = self.values()
        message = self.query_one("#set-message", Static)
        if problems:
            message.update(Text("Pas enregistré : " + " ; ".join(problems), style=RED))
            return
        settings_module.save(values, self.path)
        message.update(Text(f"Enregistré dans {self.path.name}.", style=GREEN))
        self.app.settings_changed(values)

    @on(Button.Pressed, "#set-defaults")
    def defaults(self) -> None:
        defaults = settings_module.Settings()
        for key, _, name, _, _, kind, value in settings_module.fields_of(defaults):
            widget = self.query_one(f"#set-{key}-{name}")
            widget.value = bool(value) if kind is bool else str(value)
        self.query_one("#set-message", Static).update("Valeurs par défaut affichées : « Enregistrer » pour les garder.")


# ── help ─────────────────────────────────────────────────────────────────────────────

FALLBACK_HELP = """# La console france-live

- **F1 Itinéraire** : un départ et une arrivée (arrêt ou adresse), une date de la fenêtre, une heure.
- **F2 Mise à jour** : vérifier et installer la dernière version de la livraison officielle.
- **F3 Données** : la version installée, ses jours types, ses sources et sa licence.
- **F4 Paramètres** : l'adresse du serveur, le tas du moteur, la recherche d'adresses.
"""


class HelpPane(Vertical):
    DEFAULT_CSS = """
    HelpPane #help-bar { height: 3; }
    HelpPane #help-md { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="help-bar"):
            yield Button("Ouvrir le guide PDF", id="help-pdf", variant="primary")
            yield Static("  Le même guide, avec les captures d'écran : docs/guide-console.pdf", id="help-info")
        text = GUIDE_MD.read_text(encoding="utf-8") if GUIDE_MD.exists() else FALLBACK_HELP
        yield MarkdownViewer(text, id="help-md", show_table_of_contents=GUIDE_MD.exists())

    @on(Button.Pressed, "#help-pdf")
    def open_pdf(self) -> None:
        if not open_file(GUIDE_PDF):
            self.query_one("#help-info", Static).update("  Pas encore de PDF.")
