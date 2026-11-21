"""The console: pick two stops or addresses anywhere in France, get the journey from raptor-kmp,
on the france-live version installed from the official delivery.

    python -m met_console

The engine is the real one (raptor-kmp-jvm) running in a JVM next to the interface, with one
day type loaded at a time. The time shown for each search is the raptor-kmp call alone,
measured inside the JVM. Addresses come from Photon, as in Pelo (see geocode.py), and go to
the engine as points: it walks to every stop within 500 m, as Pelo's searches do.
"""

from __future__ import annotations

import datetime as dt
import functools
import random
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, Select, Static, Switch, TabbedContent, TabPane
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from . import dataset as dataset_module
from . import geo, mapview
from . import settings as settings_module
from .backend import EngineServer, Journey, RouteResult
from .daytypes import LABELS, Plan
from .geocode import Address, Geocoder
from .loading import SPINNER, LoadingView, seconds_text
from .mapview import MapView
from .panes import DataPane, HelpPane, SettingsPane
from .places import Place, PlaceIndex
from .sync import SyncRun
from .updates import UpdatePane

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
    return f"{short_day(day)} · {kind}" + ("" if model == day else f" (≈ {model.day:02d}/{model.month:02d})")


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


class NoGeocoder:
    """Address search switched off in the settings: no address is ever suggested."""

    def search(self, text, near=None, limit=6):
        return []


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
    TITLE = "france-live · console"
    CSS = """
    #tabs { height: 1fr; }
    #route { layout: horizontal; height: 1fr; }
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
    #empty { padding: 2 2; }
    """
    BINDINGS = [
        # priority: the text inputs bind some ctrl keys themselves (ctrl+e = end of line)
        Binding("ctrl+r", "random", "Surprends-moi", priority=True),
        Binding("ctrl+e", "swap", "Inverser", priority=True),
        Binding("ctrl+t", "zoom", "Zoom carte", priority=True),
        Binding("ctrl+g", "route", "Calculer", priority=True),
        Binding("down", "to_list", show=False),
        Binding("f1", "tab('tab-route')", "Itinéraire", priority=True),
        Binding("f2", "tab('tab-update')", "Mise à jour", priority=True),
        Binding("f3", "tab('tab-data')", "Données", priority=True),
        Binding("f4", "tab('tab-settings')", "Paramètres", priority=True),
        Binding("f5", "tab('tab-help')", "Aide", priority=True),
    ]

    def __init__(self, data_root: Path, java: str | None = None, xmx: str | None = None,
                 server_factory: Callable | None = None, commune_lookup=None, outline: list | None = None,
                 geocoder=None, today: dt.date | None = None, sync_runner=SyncRun):
        """`data_root` holds everything this machine keeps: france-live/ (dataset-sync's), cache/,
        settings.json. The other arguments replace the real pieces in tests."""
        super().__init__()
        self.data_root = data_root
        self.sync_root = data_root / "france-live"
        self.cache_dir = data_root / "cache"
        self.settings_path = data_root / "settings.json"
        self.settings = settings_module.load(self.settings_path)
        self.java = java or self.settings.engine.java or None
        self.xmx = xmx or self.settings.engine.xmx
        self.server_factory = server_factory or (lambda folder: EngineServer(folder, self.java, self.xmx))
        self.commune_lookup = commune_lookup or (lambda lat, lon: geo.commune_names(self.cache_dir / "geo", lat, lon))
        self.given_outline = outline
        self.sync_runner = sync_runner
        self.today = today or dt.date.today()
        self.installed = dataset_module.installed(self.sync_root)
        self.plan: Plan | None = self.installed.plan() if self.installed else None
        self.dates = window_dates(self.plan, self.today) if self.plan else []
        self.day: dt.date | None = self.dates[0] if self.dates else None
        self.server = None
        if geocoder is None:
            geocoder = Geocoder(self.cache_dir / "geocode.json") if self.settings.routing.geocoding else NoGeocoder()
        self.geocoder = geocoder
        self.index: PlaceIndex | None = None
        self.outline: list = []
        self.chosen: dict[str, Endpoint | None] = {"from": None, "to": None}
        self.suggestions: dict[str, list[Endpoint]] = {"from": [], "to": []}
        self.places_found: dict[str, list[Place]] = {"from": [], "to": []}
        self.searched: dict[str, str] = {}  # the text each field's suggestions were computed for
        self.result: RouteResult | None = None
        self.journey: Journey | None = None
        self.zoom = True
        self.network: tuple | None = None
        self.history: deque[str] = deque(maxlen=12)
        self.rng = random.Random()
        self.changes_used = DEFAULT_CHANGES  # the limit of the result on screen
        self.busy: tuple[str, float] | None = None  # a search under way: its text, its start
        self.frame = 0
        self.loads = 0  # networks loaded since start: a new loading checklist each time

    # ── layout ───────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs", initial="tab-route" if self.installed else "tab-update"):
            with TabPane("Itinéraire", id="tab-route"):
                with Horizontal(id="route"):
                    yield from self.compose_route()
            with TabPane("Mise à jour", id="tab-update"):
                yield UpdatePane(runner=self.sync_runner, id="update")
            with TabPane("Données", id="tab-data"):
                yield DataPane(id="data")
            with TabPane("Paramètres", id="tab-settings"):
                yield SettingsPane(self.settings_path, id="settings")
            with TabPane("Aide", id="tab-help"):
                yield HelpPane(id="help")
        yield Footer()

    def network_name(self) -> str:
        return f"france-live {self.installed.version}" if self.installed else "france-live"

    def compose_route(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Label("Départ · arrêt ou adresse", classes="label")
            yield Input(placeholder="Bellecour, Châtelet, 20 rue de la Paix Paris…", id="from", disabled=True)
            yield OptionList(id="from_list")
            yield Label("Arrivée · arrêt ou adresse", classes="label")
            yield Input(placeholder="Part-Dieu, La Défense, Tour Eiffel…", id="to", disabled=True)
            yield OptionList(id="to_list")
            yield Label(self.when_text(), id="when_label", classes="label")
            yield Select(self.date_options() or [("–", "-")], value=self.dates[0].isoformat() if self.dates else "-",
                         allow_blank=False, id="day")
            with Horizontal(id="when"):
                yield Input(value="08:00", id="time", placeholder="HH:MM")
                yield Switch(id="arrive_by")
                yield Label("arriver avant", id="arrive_by_label")
            with Horizontal(id="limits"):
                yield Button("−", id="fewer")
                yield Input(value=str(self.settings.routing.default_changes), id="max_changes", type="integer", max_length=2)
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
            yield Static(Text.assemble(("Aucune version de france-live installée.\n\n", "bold"),
                                       ("F2 Mise à jour l'installe depuis la livraison officielle : le paquet complet, "
                                        "environ 45 Mo, puis chaque jour une petite différence.", "dim")), id="empty")
            yield LoadingView(self.network_name(), LOAD_STEPS, id="loader")
            yield Static("", id="summary")
            yield OptionList(id="alternatives")
            with VerticalScroll(id="legs_box"):  # an absurd journey has more legs than the screen
                yield Static("", id="legs")
            yield MapView(id="map")
            yield Static("", id="map_legend")

    def when_text(self) -> str:
        if self.plan:
            start, end = self.plan.window
            return f"Quand · données du {short_day(start)} au {short_day(end)}"
        return "Quand"

    def date_options(self) -> list[tuple[str, str]]:
        return [(date_option(d, self.plan), d.isoformat()) for d in self.dates] if self.plan else []

    def on_mount(self) -> None:
        for widget in ("#summary", "#alternatives", "#legs_box", "#map", "#map_legend"):
            self.query_one(widget).display = False
        self.query_one("#day").display = bool(self.plan)
        self.set_interval(1 / 12, self.spin)
        self.query_one("#empty").display = self.installed is None
        self.query_one(LoadingView).display = self.installed is not None
        if self.installed is not None:
            self.load()
        if self.settings.server.check_on_start:
            self.query_one("#update", UpdatePane).start(check=True)

    # ── loading ──────────────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="load")
    def load(self) -> None:
        started = time.perf_counter()
        loader = self.query_one(LoadingView)
        current = "engine"

        def step(method: str, key: str, *args) -> None:
            nonlocal current
            current = key
            self.call_from_thread(getattr(loader, method), key, *args)

        try:
            step("start", "engine", f"Java {self.xmx}")
            if self.server is None:
                self.server = self.server_factory(self.installed.dir)
            period = self.needed_period()  # the engine starts on semaine; today may be another day type
            if period:
                self.server.period(period)
            info = self.server.info
            step("done", "engine", f"{ms(info['loadMs'])} dans raptor-kmp · {info['heapMb']:.0f} Mo de tas")

            step("start", "stops")
            stops = self.server.stops()
            step("done", "stops", f"{thousands(len(stops))} arrêts")

            step("start", "places")
            index = PlaceIndex(stops)
            step("done", "places", f"{thousands(len(index))} lieux")

            step("start", "communes", "en cache, ou calculées une fois par jeu d'arrêts")
            cached = index.attach_communes(self.cache_dir, self.commune_lookup)
            step("done", "communes", "depuis le cache" if cached else "calculées et mises en cache")

            step("start", "outline")
            self.outline = self.given_outline if self.given_outline is not None else mapview.france_outline(self.cache_dir)
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
        """Which timetable a search uses: the chosen date's day type."""
        if self.plan and self.day:
            kind = self.plan.network_for(self.day) or "semaine"
            model = dt.date.fromisoformat(self.plan.days[kind])
            same = "" if model == self.day else f", celui du {short_day(model)}"
            return f"horaires du {day_text(self.day)} (réseau {LABELS[kind]}{same})"
        return ""

    def update_sub_title(self) -> None:
        info = self.server.info
        period = f" · réseau {info['period']}" if len(info.get("periods") or []) > 1 else ""
        self.sub_title = (f"{self.network_name()} · {thousands(info['stops'])} arrêts · {thousands(info['routes'])} lignes · "
                          f"{thousands(info['trips'])} courses{period} · chargé en {ms(info['loadMs'])} · "
                          f"{info['heapMb']:.0f} Mo" + (f" · {self.schedule_text()}" if self.schedule_text() else ""))
        self.query_one("#data", DataPane).show_engine(info)

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
        # A focused widget pulls its tab to the front: only when the itinerary is the one shown.
        if self.query_one("#tabs", TabbedContent).active == "tab-route":
            self.query_one("#from", Input).focus()
        self.set_timer(0.8, self.reveal)  # leave the finished checklist on screen a moment

    def reveal(self) -> None:
        self.query_one(LoadingView).display = False
        for widget in ("#summary", "#legs_box", "#map", "#map_legend"):
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
        self.searched[field] = event.value
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
        if self.searched.get(field) != event.value and self.chosen.get(field) is None:
            # Enter came before the suggestions for the latest keystrokes: compute them now.
            found = self.index.search(event.value, PLACE_LIMIT) if self.index and len(event.value.strip()) >= 2 else []
            self.places_found[field] = found
            self.fill(field, found, [])
            self.searched[field] = event.value
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
        if event.value is Select.BLANK or event.value == "-" or not self.plan:
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
                                       max_rounds=changes + 1,
                                       fallback_walk_m=(self.settings.routing.fallback_walk_m or None) if addresses else None,
                                       school=school)
        except Exception as error:  # the engine said no: show it, keep the app alive
            if "OutOfMemoryError" in str(error):
                message = (f"Pas assez de mémoire pour {limit_text(changes)} : donne plus de tas au moteur "
                           f"(F4 Paramètres, 2g par exemple).")
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
        self.query_one("#map", MapView).follow()
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
        box = self.query_one("#map", MapView)
        zoom = self.zoom and self.journey is not None
        box.show(self.journey, self.outline, zoom, self.network)
        self.query_one("#map_legend", Static).update(mapview.legend(self.journey))

    def on_resize(self) -> None:
        self.call_after_refresh(self.redraw_map)

    def action_zoom(self) -> None:
        self.zoom = not self.zoom
        self.query_one("#map", MapView).follow()
        self.redraw_map()

    # ── the other tabs ───────────────────────────────────────────────────────────────

    def action_tab(self, tab: str) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        if tabs.active != tab:
            # A focused widget pulls its own tab back to the front: let go of the focus first.
            self.set_focus(None)
            tabs.active = tab

    def settings_changed(self, values: settings_module.Settings) -> None:
        engine_changed = (values.engine.xmx, values.engine.java) != (self.settings.engine.xmx, self.settings.engine.java)
        self.settings = values
        if engine_changed and self.installed is not None:
            self.java, self.xmx = values.engine.java or None, values.engine.xmx
            self.notify(f"Le moteur redémarre avec {self.xmx} de tas.", timeout=5)
            self.switch_version()
        else:
            self.notify("Paramètres enregistrés.", timeout=4)

    def sync_finished(self, run: SyncRun) -> None:
        """After a check or an update: a new version installed goes to the itinerary and the data tab."""
        now = dataset_module.installed(self.sync_root)
        before = self.installed.version if self.installed else None
        if now is None or now.version == before:
            return
        self.installed = now
        self.query_one("#data", DataPane).show(now)
        self.notify(f"{now.version} installée : le moteur la charge.", title="Mise à jour", timeout=6)
        self.switch_version()

    def switch_version(self) -> None:
        """Load the installed version in the itinerary tab: the engine restarts on it."""
        if self.server is not None:
            self.server.close()
        self.server = None
        plan = self.installed.plan() if self.installed else None
        self.plan = plan
        self.dates = window_dates(plan, self.today) if plan else []
        self.day = self.dates[0] if self.dates else None
        self.index, self.journey, self.result = None, None, None
        self.chosen = {"from": None, "to": None}
        for field in ("from", "to"):
            box = self.query_one(f"#{field}", Input)
            with box.prevent(Input.Changed):
                box.value = ""
            box.disabled = True
        for widget in ("#go", "#random"):
            self.query_one(widget).disabled = True
        self.query_one("#when_label", Label).update(self.when_text())
        day = self.query_one("#day", Select)
        if plan:
            with day.prevent(Select.Changed):
                day.set_options(self.date_options())
                day.value = self.dates[0].isoformat()
        day.display = bool(plan)
        for widget in ("#summary", "#alternatives", "#legs_box", "#map", "#map_legend"):
            self.query_one(widget).display = False
        self.query_one("#empty").display = False
        old = self.query_one(LoadingView)
        self.loads += 1
        new = LoadingView(self.network_name(), LOAD_STEPS, id=f"loader-{self.loads}")
        self.query_one("#right").mount(new, before=old)
        old.remove()
        self.load()

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
        for update in self.query(UpdatePane):  # the widgets may be gone already
            if update.running is not None:
                update.running.stop()
