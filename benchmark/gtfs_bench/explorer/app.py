"""Terminal explorer: pick two stops or addresses anywhere in France, get the itinerary from raptor-kmp.

    python -m gtfs_bench.explorer                 # France, from data/raptor/france/bench
    python -m gtfs_bench.explorer --tier metropole:lyon

The engine is the real one (raptor-kmp-jvm) running in a JVM next to the interface, with
the network loaded once. The time shown for each search is the raptor-kmp call alone,
measured inside the JVM. Addresses come from Photon, as in Pelo (see geocode.py), and go to
the engine as points: it walks to every stop within 500 m, as Pelo's searches do.
"""

from __future__ import annotations

import datetime as dt
import functools
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
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Select, Static, Switch
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from ..horizon import LABELS, Plan
from . import mapview
from .backend import EngineServer, Journey, RouteResult
from .geocode import Address, Geocoder
from .loading import SPINNER, LoadingView, seconds_text
from .places import Place, PlaceIndex

Endpoint = Place | Address

DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")

# Changes allowed per journey. RAPTOR counts rounds (rides): rounds = changes + 1. The engine's
# default is 5 rounds; the explorer lets you go much higher, for the fun of absurd itineraries.
DEFAULT_CHANGES = 4
MAX_CHANGES = 99

# Suggestions: stops first, then addresses, as in Pelo. Few stops, so addresses stay in view.
PLACE_LIMIT = 12
GEOCODE_DELAY_S = 0.3  # Pelo's debounce: ask Photon once typing pauses
# Pelo's second try when an address finds nothing within 500 m on foot.
FALLBACK_WALK_M = 6000.0

# Start-up steps: key, label, weight = its usual seconds on France (cached communes), for the
# overall bar.
LOAD_STEPS = [
    ("engine", "Démarrage du moteur, lecture des .bin", 1.2),
    ("stops", "Liste des arrêts", 0.9),
    ("places", "Regroupement des arrêts en lieux", 3.8),
    ("communes", "Commune de chaque lieu", 0.5),
    ("outline", "Contour de la France", 0.1),
    ("warmup", "Échauffement du moteur (JIT)", 2.0),
    ("dots", "Points du réseau pour la carte", 0.1),
]
WARMUP_QUERIES = 30


SHORT_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def day_text(day: dt.date) -> str:
    return f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def short_day(day: dt.date) -> str:
    return f"{DAYS[day.weekday()][:3]}. {day.day} {SHORT_MONTHS[day.month - 1]}"


def window_dates(plan: Plan, today: dt.date) -> list[dt.date]:
    """The dates a live network answers for: from today (or the window's start) to its end."""
    start, end = plan.window
    first = max(start, today)
    return [first + dt.timedelta(days=k) for k in range((end - first).days + 1)] or [start]


def date_option(day: dt.date, plan: Plan) -> str:
    kind = plan.network_for(day) or "semaine"
    model = dt.date.fromisoformat(plan.days[kind])
    return f"{short_day(day)} · {LABELS[kind]}" + ("" if model == day else f" (comme le {short_day(model)})")


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


def km(meters: float | None) -> str:
    return f"{(meters or 0) / 1000:g} km".replace(".", ",")


def engine_endpoint(endpoint: Endpoint) -> list[int] | dict:
    """What the engine is sent for a choice: a place's stop ids, or an address's point."""
    return endpoint.endpoint() if isinstance(endpoint, Address) else endpoint.ids


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
    #when, #limits, #options { height: 3; }
    #time { width: 12; }
    #arrive_by_label, #limits_label, #school_label { padding: 1 1; }
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
                 commune_lookup=None, outline: list | None = None, geocoder=None, plan: Plan | None = None,
                 today: dt.date | None = None):
        super().__init__()
        self.commune_lookup, self.given_outline = commune_lookup, outline  # injected in tests
        self.data_dir, self.tier_name, self.java, self.xmx = data_dir, tier_name, java, xmx
        self.cache_dir, self.reference_day = cache_dir, reference_day
        # A live network (gtfs_bench.refresh): any date of its window, each served by its day type.
        self.plan = plan
        self.dates = window_dates(plan, today or dt.date.today()) if plan else []
        self.day: dt.date | None = self.dates[0] if self.dates else reference_day
        self.server = server  # injected in tests
        self.geocoder = geocoder if geocoder is not None else Geocoder(cache_dir / "geocode.json" if cache_dir else None)
        self.index: PlaceIndex | None = None
        self.outline: list = []
        self.chosen: dict[str, Endpoint | None] = {"from": None, "to": None}
        self.suggestions: dict[str, list[Endpoint]] = {"from": [], "to": []}
        self.places_found: dict[str, list[Place]] = {"from": [], "to": []}
        self.result: RouteResult | None = None
        self.journey: Journey | None = None
        self.zoom = True
        self.network: tuple | None = None
        self.history: deque[str] = deque(maxlen=12)
        self.rng = random.Random()
        self.changes_used = DEFAULT_CHANGES  # the limit of the result on screen
        self.busy: tuple[str, float] | None = None  # a search under way: its text, its start
        self.frame = 0

    # ── layout ───────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="left"):
            yield Label("Départ · arrêt ou adresse", classes="label")
            yield Input(placeholder="Bellecour, Châtelet, 20 rue de la Paix Paris…", id="from", disabled=True)
            yield OptionList(id="from_list")
            yield Label("Arrivée · arrêt ou adresse", classes="label")
            yield Input(placeholder="Part-Dieu, La Défense, Tour Eiffel…", id="to", disabled=True)
            yield OptionList(id="to_list")
            if self.plan:
                start, end = self.plan.window
                when = f"Quand · données du {short_day(start)} au {short_day(end)}"
            else:
                when = f"Quand · horaires du {day_text(self.reference_day)}" if self.reference_day else "Quand"
            yield Label(when, id="when_label", classes="label")
            if self.plan:
                yield Select([(date_option(d, self.plan), d.isoformat()) for d in self.dates],
                             value=self.dates[0].isoformat(), allow_blank=False, id="day")
            with Horizontal(id="when"):
                yield Input(value="08:00", id="time", placeholder="HH:MM")
                yield Switch(id="arrive_by")
                yield Label("arriver avant", id="arrive_by_label")
            with Horizontal(id="limits"):
                yield Button("−", id="fewer")
                yield Input(value=str(DEFAULT_CHANGES), id="max_changes", type="integer", max_length=2)
                yield Button("+", id="more")
                yield Label("correspondances max", id="limits_label")
            with Horizontal(id="options"):
                yield Switch(value=True, id="school", disabled=True)
                yield Label("lignes scolaires", id="school_label")
            with Horizontal(id="buttons"):
                yield Button("Calculer", id="go", variant="primary", disabled=True)
                yield Button("Surprends-moi", id="random", disabled=True)
                yield Button("⇄", id="swap")
            yield Static("", id="history")
        with Vertical(id="right"):
            yield LoadingView(self.tier_name, LOAD_STEPS, id="loader")
            yield Static("", id="summary")
            yield OptionList(id="alternatives")
            with VerticalScroll(id="legs_box"):  # an absurd journey has more legs than the screen
                yield Static("", id="legs")
            yield Static("", id="map")
        yield Footer()

    def on_mount(self) -> None:
        for widget in ("#summary", "#alternatives", "#legs_box", "#map"):
            self.query_one(widget).display = False
        self.set_interval(1 / 12, self.spin)
        self.load()

    # ── loading ──────────────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="load")
    def load(self) -> None:
        started = time.perf_counter()
        loader = self.query_one("#loader", LoadingView)
        current = "engine"

        def step(method: str, key: str, *args) -> None:
            nonlocal current
            current = key
            self.call_from_thread(getattr(loader, method), key, *args)

        try:
            step("start", "engine", f"Java {self.xmx}")
            if self.server is None:
                self.server = EngineServer(self.data_dir, self.java, self.xmx)
            info = self.server.info
            step("done", "engine", f"{ms(info['loadMs'])} dans raptor-kmp · {info['heapMb']:.0f} Mo de tas")

            step("start", "stops")
            stops = self.server.stops()
            step("done", "stops", f"{thousands(len(stops))} arrêts")

            step("start", "places")
            index = PlaceIndex(stops)
            step("done", "places", f"{thousands(len(index))} lieux")

            # A tier's folder is <tier>/bench; a live network's is the network's own folder.
            stem = self.data_dir.parent.name if (self.data_dir / "routes.bin").exists() else self.data_dir.name
            cache = self.cache_dir / f"{stem}-communes.json" if self.cache_dir else None
            cached = cache is not None and cache.exists()
            step("start", "communes", "depuis le cache" if cached else "première fois : quelques secondes, puis en cache")
            index.attach_communes(cache, self.commune_lookup)
            step("done", "communes", "depuis le cache" if cached else "calculées et mises en cache")

            step("start", "outline")
            self.outline = self.given_outline if self.given_outline is not None else mapview.france_outline(
                self.cache_dir / "france-outline.json" if self.cache_dir else None)
            step("done", "outline", f"{sum(len(ring) for ring in self.outline)} points")

            step("start", "warmup")
            warm = random.Random(7)
            for i in range(WARMUP_QUERIES):
                a, b = index.random_pair(warm)
                self.server.route(a.ids, b.ids, 8 * 3600)
                step("progress", "warmup", (i + 1) / WARMUP_QUERIES, f"{i + 1}/{WARMUP_QUERIES} recherches")
            step("done", "warmup", f"{WARMUP_QUERIES} recherches au hasard")

            step("start", "dots")
            self.network = (np.array([p.lat for p in index.places]), np.array([p.lon for p in index.places]))
            step("done", "dots", f"{thousands(len(index))} points")
        except Exception as error:  # say which step broke, keep the window open
            self.call_from_thread(loader.fail, current, f"Échec : {error}")
            return
        self.index = index
        self.call_from_thread(self.ready, time.perf_counter() - started)

    def status(self, text: str) -> None:
        self.busy = None
        self.query_one("#summary", Static).update(Text(text, style="italic"))

    def spin(self) -> None:
        """While a search runs, a spinner and its time so far in the summary."""
        if self.busy is None:
            return
        self.frame += 1
        text, since = self.busy
        line = Text(f"{SPINNER[self.frame % len(SPINNER)]} ", style="bold #eb6834")
        line.append(text, style="italic")
        elapsed = time.perf_counter() - since
        if elapsed > 0.25:
            line.append(f"  {seconds_text(elapsed)}", style="dim")
        self.query_one("#summary", Static).update(line)

    def schedule_text(self) -> str:
        """Which timetable a search uses: the reference day, or a live network's day type."""
        if self.plan and self.day:
            kind = self.plan.network_for(self.day) or "semaine"
            model = dt.date.fromisoformat(self.plan.days[kind])
            same = "" if model == self.day else f", celui du {short_day(model)}"
            return f"horaires du {day_text(self.day)} (réseau {LABELS[kind]}{same})"
        return f"horaires du {day_text(self.reference_day)}" if self.reference_day else ""

    def update_sub_title(self) -> None:
        info = self.server.info
        period = f" · réseau {info['period']}" if len(info.get("periods") or []) > 1 else ""
        self.sub_title = (f"{self.tier_name} · {thousands(info['stops'])} arrêts · {thousands(info['routes'])} lignes · "
                          f"{thousands(info['trips'])} courses{period} · chargé en {ms(info['loadMs'])} · "
                          f"{info['heapMb']:.0f} Mo" + (f" · {self.schedule_text()}" if self.schedule_text() else ""))

    def ready(self, seconds: float) -> None:
        info = self.server.info
        self.update_sub_title()
        for widget in ("#from", "#to", "#go", "#random"):
            self.query_one(widget).disabled = False
        # School lines can be left out when the network comes with its list (gtfs_bench.school).
        school_trips = info.get("schoolTrips", 0)
        if info.get("schoolRoutes", 0):
            self.query_one("#school", Switch).disabled = False
            self.query_one("#school_label", Label).update(f"lignes scolaires · {thousands(school_trips)} courses")
        else:
            self.query_one("#school_label", Label).update("lignes scolaires · pas de liste pour ce réseau")
        self.status(f"Prêt en {seconds:.1f} s. Choisis un départ et une arrivée, ou Ctrl+R pour un trajet au hasard.")
        self.query_one("#from", Input).focus()
        self.set_timer(0.8, self.reveal)  # leave the finished checklist on screen a moment

    def reveal(self) -> None:
        self.query_one("#loader").display = False
        for widget in ("#summary", "#legs_box", "#map"):
            self.query_one(widget).display = True
        self.call_after_refresh(self.redraw_map)

    # ── choosing stops ───────────────────────────────────────────────────────────────

    @on(Input.Changed, "#from, #to")
    def search(self, event: Input.Changed) -> None:
        field = event.input.id
        place = self.chosen.get(field)
        if place is not None and event.value == place.name:
            return
        self.chosen[field] = None
        found = self.index.search(event.value, PLACE_LIMIT) if self.index and len(event.value.strip()) >= 2 else []
        self.places_found[field] = found
        self.fill(field, found, [])
        other = self.chosen["to" if field == "from" else "from"]
        near = (other.lat, other.lon) if other is not None else None
        self.run_worker(functools.partial(self.find_addresses, field, event.value, near), thread=True,
                        exclusive=True, group=f"geocode-{field}")

    def find_addresses(self, field: str, text: str, near: tuple[float, float] | None) -> None:
        """Ask Photon once typing pauses; a newer keystroke cancels this worker."""
        time.sleep(GEOCODE_DELAY_S)
        worker = get_current_worker()
        if worker.is_cancelled:
            return
        found = self.geocoder.search(text, near)
        if not worker.is_cancelled:
            self.call_from_thread(self.add_addresses, field, text, found)

    def add_addresses(self, field: str, text: str, addresses: list[Address]) -> None:
        if self.query_one(f"#{field}", Input).value != text or self.chosen[field] is not None:
            return  # typed on, or picked something, meanwhile
        self.fill(field, self.places_found[field], addresses)

    def fill(self, field: str, places: list[Place], addresses: list[Address]) -> None:
        """Stops, then a separator and the addresses. Option ids index self.suggestions."""
        self.suggestions[field] = [*places, *addresses]
        options = self.query_one(f"#{field}_list", OptionList)
        kept = options.highlighted if places else None
        options.clear_options()
        items = [Option(p.label(), id=str(i)) for i, p in enumerate(places)]
        if addresses:
            items.append(Option(Text("Adresses · Photon", style="dim italic"), id="addresses", disabled=True))
            items += [Option(a.option_text(), id=str(len(places) + i)) for i, a in enumerate(addresses)]
        options.add_options(items)
        if places:
            options.highlighted = kept if kept is not None and kept < len(places) else 0
        elif addresses:
            options.highlighted = 1  # the first address, under the separator

    def highlighted_suggestion(self, field: str) -> Endpoint | None:
        options = self.query_one(f"#{field}_list", OptionList)
        if options.highlighted is not None:
            option = options.get_option_at_index(options.highlighted)
            if option.id and option.id.isdigit():
                return self.suggestions[field][int(option.id)]
        return self.suggestions[field][0] if self.suggestions[field] else None

    @on(Input.Submitted, "#from, #to")
    def pick_first(self, event: Input.Submitted) -> None:
        field = event.input.id
        choice = self.highlighted_suggestion(field)
        if choice is not None:
            self.choose(field, choice)

    @on(OptionList.OptionSelected, "#from_list, #to_list")
    def pick(self, event: OptionList.OptionSelected) -> None:
        field = event.option_list.id.removesuffix("_list")
        if event.option.id and event.option.id.isdigit():
            self.choose(field, self.suggestions[field][int(event.option.id)])

    def choose(self, field: str, place: Endpoint) -> None:
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
        limit = f" (≤ {changes} corresp.)" if changes != DEFAULT_CHANGES else ""
        school = self.query_one("#school", Switch).value
        limit += "" if school else " sans scolaires"
        self.busy = (f"Calcul {origin.name[:30]} → {destination.name[:30]}{limit}…", time.perf_counter())
        self.spin()
        self.compute(origin, destination, when, arrive_by, changes, school)

    @on(Input.Submitted, "#time, #max_changes")
    def time_entered(self) -> None:
        self.action_route()

    @on(Switch.Changed, "#school")
    def school_switched(self) -> None:
        if self.chosen["from"] and self.chosen["to"]:
            self.action_route()

    @on(Select.Changed, "#day")
    def day_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.day = dt.date.fromisoformat(str(event.value))
        if self.server is not None and self.index is not None:
            self.update_sub_title()
            if self.chosen["from"] and self.chosen["to"]:
                self.action_route()

    def needed_period(self) -> str | None:
        """The day type the chosen date needs, when the engine has another one loaded."""
        if not (self.plan and self.day and self.server):
            return None
        kind = self.plan.network_for(self.day)
        return kind if kind and kind != self.server.info.get("period") else None

    @on(Button.Pressed, "#fewer, #more")
    def step_changes(self, event: Button.Pressed) -> None:
        box = self.query_one("#max_changes", Input)
        current = parse_changes(box.value)
        step = 1 if event.button.id == "more" else -1
        box.value = str(DEFAULT_CHANGES if current is None else min(MAX_CHANGES, max(0, current + step)))
        if self.chosen["from"] and self.chosen["to"]:
            self.action_route()

    @work(thread=True, exclusive=True, group="route")
    def compute(self, origin: Endpoint, destination: Endpoint, when: int, arrive_by: bool, changes: int,
                school: bool = True) -> None:
        addresses = isinstance(origin, Address) or isinstance(destination, Address)
        try:
            period = self.needed_period()
            if period:  # another day type: the engine swaps networks first (about a second)
                self.busy = (f"Chargement des horaires {LABELS[period]}…", time.perf_counter())
                self.server.period(period)
                self.call_from_thread(self.update_sub_title)
                self.busy = (f"Calcul {origin.name[:30]} → {destination.name[:30]}…", time.perf_counter())
            result = self.server.route(engine_endpoint(origin), engine_endpoint(destination), when, arrive_by,
                                       max_rounds=changes + 1, fallback_walk_m=FALLBACK_WALK_M if addresses else None,
                                       school=school)
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

    def show(self, origin: Endpoint, destination: Endpoint, when: int, arrive_by: bool, changes: int,
             result: RouteResult) -> None:
        self.result, self.changes_used, self.busy = result, changes, None
        journeys = sorted(result.journeys, key=lambda j: (j.changes, j.arrival))
        self.journey = result.best(arrive_by)
        alternatives = self.query_one("#alternatives", OptionList)
        alternatives.clear_options()
        verb = "arrivée avant" if arrive_by else "départ à"
        limit = f" ≤{changes}" if changes != DEFAULT_CHANGES else ""
        limit += " ¬scol" if result.school_blocked else ""
        self.history.appendleft(f"{ms(result.ms):>9}  {origin.name[:15]} → {destination.name[:15]}{limit}")
        self.query_one("#history", Static).update(Text("Derniers calculs\n", style="bold") + Text("\n".join(self.history)))
        if self.journey is None:
            summary = Text(f"Aucun itinéraire, {verb} {hhmm(when)}", style="bold #e34948")
            summary.append(f"  ·  {self.schedule_text()}\n" if self.schedule_text() else "\n", style="dim")
            summary.append(f"calculé en {ms(result.ms)} · {limit_text(changes)}"
                           + (" · sans les lignes scolaires" if result.school_blocked else "") + "\n", style="dim")
            if result.fallback:
                summary.append(f"même en marchant jusqu'à {km(result.walk_radius)} depuis l'adresse", style="dim")
            else:
                summary.append("essaie plus de correspondances" if changes < 10 else "ni même en zigzaguant", style="dim")
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
        day = f" · {self.schedule_text()}" if self.schedule_text() else ""
        school = " · sans les lignes scolaires" if result.school_blocked else ""
        summary.append(limit_text(self.changes_used) + school + day, style="dim")
        if result.fallback:
            summary.append(f"\nrien d'utile à 500 m à pied : marche élargie à {km(result.walk_radius)}, comme Pelo",
                           style="#eda100")
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
