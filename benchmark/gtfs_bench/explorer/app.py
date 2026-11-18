"""Terminal explorer: pick two stops anywhere in France, get the itinerary from raptor-kmp.

    python -m gtfs_bench.explorer                 # France, from data/raptor/france/bench
    python -m gtfs_bench.explorer --tier metropole:lyon

The engine is the real one (raptor-kmp-jvm) running in a JVM next to the interface, with
the network loaded once. The time shown for each search is the raptor-kmp call alone,
measured inside the JVM.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import time

import numpy as np
from collections import deque
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Static, Switch
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from . import mapview
from .backend import EngineServer, Journey, RouteResult
from .places import Place, PlaceIndex

DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")

# Changes allowed per journey. RAPTOR counts rounds (rides): rounds = changes + 1. The engine's
# default is 5 rounds; the explorer lets you go much higher, for the fun of absurd itineraries.
DEFAULT_CHANGES = 4
MAX_CHANGES = 99


def day_text(day: dt.date) -> str:
    return f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def parse_changes(text: str) -> int | None:
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if 0 <= value <= MAX_CHANGES else None


def limit_text(changes: int) -> str:
    rounds = f"{changes + 1} tour{'s' if changes else ''} RAPTOR"
    if changes == 0:
        return f"trajets directs seulement ({rounds})"
    return f"au plus {changes} correspondance{'s' if changes > 1 else ''} ({rounds})"


def hhmm(seconds: int) -> str:
    day, rest = divmod(seconds, 86400)
    text = f"{rest // 3600:02d}:{(rest % 3600) // 60:02d}"
    return text + (f" (+{day} j)" if day else "")


def duration(seconds: int) -> str:
    minutes = round(seconds / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def ms(value: float) -> str:
    return (f"{value:.1f}" if value < 100 else f"{value:.0f}").replace(".", ",") + " ms"


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def parse_time(text: str) -> int | None:
    try:
        h, m = (int(x) for x in text.strip().replace("h", ":").split(":")[:2])
    except ValueError:
        return None
    return h * 3600 + m * 60 if 0 <= h < 48 and 0 <= m < 60 else None


def journey_summary(journey: Journey, arrive_by: bool) -> str:
    changes = journey.changes
    change_text = "direct" if changes == 0 else f"{changes} correspondance{'s' if changes > 1 else ''}"
    return f"{hhmm(journey.departure)} → {hhmm(journey.arrival)}  ·  {duration(journey.arrival - journey.departure)}  ·  {change_text}"


def legs_table(journey: Journey) -> Table:
    table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
    table.add_column("heure", style="bold", no_wrap=True, width=13)
    table.add_column("ligne", no_wrap=True, width=12)
    table.add_column("trajet", ratio=1)
    ride = 0
    for leg in journey.legs:
        times = f"{hhmm(leg.departure)} → {hhmm(leg.arrival)}"
        if leg.walk:
            what = "correspondance sur place" if leg.from_name == leg.to_name else f"{leg.from_name} → {leg.to_name}"
            table.add_row(Text(times, style="dim"), Text(" à pied ", style="italic #c3c2b7"),
                          Text(f"{what}  ({duration(leg.arrival - leg.departure)})", style="dim"))
            continue
        colour = mapview.ride_colour(ride)
        ride += 1
        badge = Text(f" {leg.route or '?'} ", style=f"bold #ffffff on {colour}")
        detail = Text(f"{leg.from_name} → {leg.to_name}")
        extras = [f"{leg.stops + 1} arrêt{'s' if leg.stops else ''}"]
        if leg.direction:
            extras.append(f"dir. {leg.direction}")
        detail.append("\n" + "  ·  ".join(extras), style="dim")
        table.add_row(times, badge, detail)
    return table


class Explorer(App):
    TITLE = "raptor-kmp · explorateur"
    CSS = """
    Screen { layout: horizontal; }
    #left { width: 52; padding: 0 1; border-right: solid $panel-lighten-2; }
    #right { padding: 0 1; }
    .label { margin-top: 1; color: $text-muted; }
    #from_list, #to_list { height: 7; border: none; background: $boost; }
    #when, #limits { height: 3; }
    #time { width: 12; }
    #arrive_by_label, #limits_label { padding: 1 1; }
    #fewer, #more { min-width: 5; width: 5; }
    #max_changes { width: 8; }
    #buttons { height: 3; margin-top: 1; }
    #buttons Button { min-width: 10; margin-right: 1; }
    #history { margin-top: 1; color: $text-muted; height: 1fr; }
    #summary { height: 5; padding: 1 1 0 1; background: $boost; }
    #alternatives { height: auto; max-height: 6; border: none; }
    #legs_box { height: auto; max-height: 50%; margin-top: 1; }
    #legs { height: auto; }
    #map { height: 1fr; margin-top: 1; }
    """
    BINDINGS = [
        # priority: the text inputs bind some ctrl keys themselves (ctrl+e = end of line)
        Binding("ctrl+r", "random", "Surprends-moi", priority=True),
        Binding("ctrl+e", "swap", "Inverser", priority=True),
        Binding("ctrl+t", "zoom", "Zoom carte", priority=True),
        Binding("ctrl+g", "route", "Calculer", priority=True),
        Binding("down", "to_list", show=False),
    ]

    def __init__(self, data_dir: Path, tier_name: str, java: str | None = None, xmx: str = "2g",
                 cache_dir: Path | None = None, reference_day: dt.date | None = None, server=None,
                 commune_lookup=None, outline: list | None = None):
        super().__init__()
        self.commune_lookup, self.given_outline = commune_lookup, outline  # injected in tests
        self.data_dir, self.tier_name, self.java, self.xmx = data_dir, tier_name, java, xmx
        self.cache_dir, self.reference_day = cache_dir, reference_day
        self.server = server  # injected in tests
        self.index: PlaceIndex | None = None
        self.outline: list = []
        self.chosen: dict[str, Place | None] = {"from": None, "to": None}
        self.suggestions: dict[str, list[Place]] = {"from": [], "to": []}
        self.result: RouteResult | None = None
        self.journey: Journey | None = None
        self.zoom = True
        self.network: tuple | None = None
        self.history: deque[str] = deque(maxlen=12)
        self.rng = random.Random()
        self.changes_used = DEFAULT_CHANGES  # the limit of the result on screen

    # ── layout ───────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="left"):
            yield Label("Départ", classes="label")
            yield Input(placeholder="Bellecour, Châtelet, Gare de Brest…", id="from", disabled=True)
            yield OptionList(id="from_list")
            yield Label("Arrivée", classes="label")
            yield Input(placeholder="Part-Dieu, La Défense…", id="to", disabled=True)
            yield OptionList(id="to_list")
            when = f"Quand · horaires du {day_text(self.reference_day)}" if self.reference_day else "Quand"
            yield Label(when, id="when_label", classes="label")
            with Horizontal(id="when"):
                yield Input(value="08:00", id="time", placeholder="HH:MM")
                yield Switch(id="arrive_by")
                yield Label("arriver avant", id="arrive_by_label")
            with Horizontal(id="limits"):
                yield Button("−", id="fewer")
                yield Input(value=str(DEFAULT_CHANGES), id="max_changes", type="integer", max_length=2)
                yield Button("+", id="more")
                yield Label("correspondances max", id="limits_label")
            with Horizontal(id="buttons"):
                yield Button("Calculer", id="go", variant="primary", disabled=True)
                yield Button("Surprends-moi", id="random", disabled=True)
                yield Button("⇄", id="swap")
            yield Static("", id="history")
        with Vertical(id="right"):
            yield Static("Chargement du moteur…", id="summary")
            yield OptionList(id="alternatives")
            with VerticalScroll(id="legs_box"):  # an absurd journey has more legs than the screen
                yield Static("", id="legs")
            yield Static("", id="map")
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    # ── loading ──────────────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="load")
    def load(self) -> None:
        started = time.perf_counter()
        self.call_from_thread(self.status, "Chargement du réseau dans raptor-kmp…")
        if self.server is None:
            self.server = EngineServer(self.data_dir, self.java, self.xmx)
        info = self.server.info
        self.call_from_thread(self.status, f"Réseau chargé en {ms(info['loadMs'])}. Indexation des {thousands(info['stops'])} arrêts…")
        index = PlaceIndex(self.server.stops())
        cache = self.cache_dir / f"{self.data_dir.parent.name}-communes.json" if self.cache_dir else None
        self.call_from_thread(self.status, f"{thousands(len(index))} lieux. Communes (calculées une fois, puis en cache)…")
        index.attach_communes(cache, self.commune_lookup)
        self.outline = self.given_outline if self.given_outline is not None else mapview.france_outline(
            self.cache_dir / "france-outline.json" if self.cache_dir else None)
        self.call_from_thread(self.status, "Échauffement du moteur (JIT)…")
        warm = random.Random(7)
        for _ in range(30):
            a, b = index.random_pair(warm)
            self.server.route(a.ids, b.ids, 8 * 3600)
        self.network = (np.array([p.lat for p in index.places]), np.array([p.lon for p in index.places]))
        self.index = index
        self.call_from_thread(self.ready, time.perf_counter() - started)

    def status(self, text: str) -> None:
        self.query_one("#summary", Static).update(Text(text, style="italic"))

    def ready(self, seconds: float) -> None:
        info = self.server.info
        day = f" · horaires du {day_text(self.reference_day)}" if self.reference_day else ""
        self.sub_title = (f"{self.tier_name} · {thousands(info['stops'])} arrêts · {thousands(info['routes'])} lignes · "
                          f"{thousands(info['trips'])} courses · chargé en {ms(info['loadMs'])} · {info['heapMb']:.0f} Mo{day}")
        for widget in ("#from", "#to", "#go", "#random"):
            self.query_one(widget).disabled = False
        self.status(f"Prêt en {seconds:.1f} s. Choisis un départ et une arrivée, ou Ctrl+R pour un trajet au hasard.")
        self.redraw_map()
        self.query_one("#from", Input).focus()

    # ── choosing stops ───────────────────────────────────────────────────────────────

    @on(Input.Changed, "#from, #to")
    def search(self, event: Input.Changed) -> None:
        field = event.input.id
        place = self.chosen.get(field)
        if place is not None and event.value == place.name:
            return
        self.chosen[field] = None
        found = self.index.search(event.value, 30) if self.index and len(event.value.strip()) >= 2 else []
        self.suggestions[field] = found
        options = self.query_one(f"#{field}_list", OptionList)
        options.clear_options()
        options.add_options([Option(p.label(), id=str(i)) for i, p in enumerate(found)])
        if found:
            options.highlighted = 0

    @on(Input.Submitted, "#from, #to")
    def pick_first(self, event: Input.Submitted) -> None:
        field = event.input.id
        options = self.query_one(f"#{field}_list", OptionList)
        index = options.highlighted if options.highlighted is not None else 0
        if self.suggestions[field]:
            self.choose(field, self.suggestions[field][min(index, len(self.suggestions[field]) - 1)])

    @on(OptionList.OptionSelected, "#from_list, #to_list")
    def pick(self, event: OptionList.OptionSelected) -> None:
        field = event.option_list.id.removesuffix("_list")
        self.choose(field, self.suggestions[field][int(event.option.id)])

    def choose(self, field: str, place: Place) -> None:
        self.chosen[field] = place
        box = self.query_one(f"#{field}", Input)
        with box.prevent(Input.Changed):
            box.value = place.name
        self.query_one(f"#{field}_list", OptionList).clear_options()
        if field == "from" and self.chosen["to"] is None:
            self.query_one("#to", Input).focus()
        elif self.chosen["from"] and self.chosen["to"]:
            self.action_route()

    def action_to_list(self) -> None:
        focused = self.focused
        if isinstance(focused, Input) and focused.id in ("from", "to"):
            self.query_one(f"#{focused.id}_list", OptionList).focus()

    # ── routing ──────────────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#go")
    def action_route(self) -> None:
        origin, destination = self.chosen["from"], self.chosen["to"]
        if not (origin and destination and self.server and self.index):
            self.status("Choisis d'abord un départ et une arrivée dans les listes.")
            return
        when = parse_time(self.query_one("#time", Input).value)
        if when is None:
            self.status("Heure illisible : écris par exemple 08:15.")
            return
        arrive_by = self.query_one("#arrive_by", Switch).value
        changes = parse_changes(self.query_one("#max_changes", Input).value)
        if changes is None:
            self.status(f"Correspondances max : un nombre de 0 à {MAX_CHANGES}.")
            return
        self.status(f"Calcul {origin.name} → {destination.name}, {limit_text(changes)}…")
        self.compute(origin, destination, when, arrive_by, changes)

    @on(Input.Submitted, "#time, #max_changes")
    def time_entered(self) -> None:
        self.action_route()

    @on(Button.Pressed, "#fewer, #more")
    def step_changes(self, event: Button.Pressed) -> None:
        box = self.query_one("#max_changes", Input)
        current = parse_changes(box.value)
        step = 1 if event.button.id == "more" else -1
        box.value = str(DEFAULT_CHANGES if current is None else min(MAX_CHANGES, max(0, current + step)))
        if self.chosen["from"] and self.chosen["to"]:
            self.action_route()

    @work(thread=True, exclusive=True, group="route")
    def compute(self, origin: Place, destination: Place, when: int, arrive_by: bool, changes: int) -> None:
        try:
            result = self.server.route(origin.ids, destination.ids, when, arrive_by, max_rounds=changes + 1)
        except Exception as error:  # the engine said no: show it, keep the app alive
            if "OutOfMemoryError" in str(error):
                message = (f"Pas assez de mémoire pour {limit_text(changes)} : relance l'explorateur avec "
                           f"un tas plus gros (--xmx 2g, 4g…).")
            else:
                message = f"Erreur du moteur : {error}"
            self.call_from_thread(self.status, message)
            return
        if get_current_worker().is_cancelled:  # a newer search was asked for meanwhile
            return
        self.call_from_thread(self.show, origin, destination, when, arrive_by, changes, result)

    def show(self, origin: Place, destination: Place, when: int, arrive_by: bool, changes: int,
             result: RouteResult) -> None:
        self.result, self.changes_used = result, changes
        journeys = sorted(result.journeys, key=lambda j: (j.changes, j.arrival))
        self.journey = result.best(arrive_by)
        alternatives = self.query_one("#alternatives", OptionList)
        alternatives.clear_options()
        verb = "arrivée avant" if arrive_by else "départ à"
        limit = f" ≤{changes}" if changes != DEFAULT_CHANGES else ""
        self.history.appendleft(f"{ms(result.ms):>9}  {origin.name[:15]} → {destination.name[:15]}{limit}")
        self.query_one("#history", Static).update(Text("Derniers calculs\n", style="bold") + Text("\n".join(self.history)))
        if self.journey is None:
            summary = Text(f"Aucun itinéraire, {verb} {hhmm(when)}\n", style="bold #e34948")
            summary.append(f"calculé en {ms(result.ms)} · {limit_text(changes)}\n", style="dim")
            summary.append("sans TGV ni Intercités pour l'instant · essaie plus de correspondances", style="dim")
            self.query_one("#summary", Static).update(summary)
            self.query_one("#legs", Static).update("")
        else:
            for i, journey in enumerate(journeys):
                alternatives.add_option(Option(f"{journey_summary(journey, arrive_by)}", id=str(i)))
            alternatives.highlighted = journeys.index(self.journey)
            self.render_journey(self.journey, result, arrive_by)
        # A list of one would only repeat the summary: show it when there is a choice.
        alternatives.display = len(journeys) > 1
        self.redraw_map()

    @on(OptionList.OptionSelected, "#alternatives")
    @on(OptionList.OptionHighlighted, "#alternatives")
    def pick_alternative(self, event) -> None:
        if not self.result or event.option is None:
            return
        journeys = sorted(self.result.journeys, key=lambda j: (j.changes, j.arrival))
        self.journey = journeys[int(event.option.id)]
        self.render_journey(self.journey, self.result, self.query_one("#arrive_by", Switch).value)
        self.redraw_map()

    def render_journey(self, journey: Journey, result: RouteResult, arrive_by: bool) -> None:
        summary = Text(journey_summary(journey, arrive_by) + "\n", style="bold")
        count = len(result.journeys)
        summary.append(f"calculé en {ms(result.ms)} par raptor-kmp · {count} itinéraire{'s' if count > 1 else ''} "
                       f"{'optimaux' if count > 1 else 'optimal'} (moins de changements ↔ plus tôt)\n", style="#1baf7a")
        day = f" · horaires du {day_text(self.reference_day)}" if self.reference_day else ""
        summary.append(limit_text(self.changes_used) + day, style="dim")
        self.query_one("#summary", Static).update(summary)
        self.query_one("#legs", Static).update(legs_table(journey))
        self.query_one("#legs_box", VerticalScroll).scroll_home(animate=False)

    # ── map and little actions ───────────────────────────────────────────────────────

    def redraw_map(self) -> None:
        box = self.query_one("#map", Static)
        cols, rows = max(box.size.width, 20), max(box.size.height, 8)
        zoom = self.zoom and self.journey is not None
        drawing = mapview.draw(cols, rows, self.journey, self.outline, zoom, self.network)
        box.update(drawing)

    def on_resize(self) -> None:
        self.call_after_refresh(self.redraw_map)

    def action_zoom(self) -> None:
        self.zoom = not self.zoom
        self.redraw_map()

    @on(Button.Pressed, "#swap")
    def action_swap(self) -> None:
        a, b = self.chosen["from"], self.chosen["to"]
        for field, place in (("from", b), ("to", a)):
            self.chosen[field] = place
            box = self.query_one(f"#{field}", Input)
            with box.prevent(Input.Changed):
                box.value = place.name if place else ""
        if a and b:
            self.action_route()

    @on(Button.Pressed, "#random")
    def action_random(self) -> None:
        if not self.index:
            return
        a, b = self.index.random_pair(self.rng)
        for field, place in (("from", a), ("to", b)):
            self.chosen[field] = place
            box = self.query_one(f"#{field}", Input)
            with box.prevent(Input.Changed):
                box.value = place.name
            self.query_one(f"#{field}_list", OptionList).clear_options()
        self.query_one("#time", Input).value = f"{self.rng.randint(6, 20):02d}:{self.rng.choice((0, 15, 30, 45)):02d}"
        self.action_route()

    def on_unmount(self) -> None:
        if self.server is not None:
            self.server.close()


def reference_day(results_dir: Path) -> dt.date | None:
    path = results_dir / "reference_day.json"
    try:
        return dt.date.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["reference_date"])
    except (OSError, KeyError, ValueError):
        return None
