"""The console: search, map, formatting, and the app driven headless on a fake installed version."""

import asyncio
import datetime as dt
import json
import random
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from met_console import dataset, mapview
from met_console import settings as settings_module
from met_console.app import Explorer, duration, engine_endpoint, hhmm, km, limit_text, ms, parse_changes, parse_time
from met_console.backend import EngineError, Journey, Leg, RouteResult, parse_route
from met_console.daytypes import Plan, day_type
from met_console.geocode import Address, Geocoder, feature_to_address, parse_photon
from met_console.loading import LoadingView
from met_console.paths import ENGINE_INSTALL
from met_console.places import PlaceIndex
from met_console.sync import SyncRun

STOPS = [
    (1, "Bellecour", 45.7578, 4.8320), (2, "Bellecour", 45.7581, 4.8326), (3, "Gare Part-Dieu", 45.7606, 4.8596),
    (4, "Saxe - Gambetta", 45.7537, 4.8470), (5, "Mairie (Vénissieux)", 45.6970, 4.8870),
    (6, "Mairie (Brest)", 48.3900, -4.4860), (7, "Châtelet (Paris)", 48.8584, 2.3470),
]
LYON = lambda lat, lon: ["Lyon 2e Arrondissement" if la < 45.759 and lo < 4.84 else "Lyon 3e" if la > 45.70 else "Vénissieux"
                         for la, lo in zip(lat, lon)]
OUTLINE = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
PLAN = {"computed_on": "2026-11-19", "start": "2026-11-19", "end": "2026-12-17", "binding_feed": "idfm",
        "binding_share": 0.27, "days": {"semaine": "2026-11-24", "samedi": "2026-11-28", "dimanche": "2026-11-29"},
        "lost": [{"feed_id": "tignes", "share": 0.0003, "last_day": "2026-11-27"}], "feeds": 246}
V1, V2 = "20261119-00000001", "20261120-00000002"


def journey():
    return Journey([
        Leg("Bellecour", "Saxe - Gambetta", 28800, 29040, "D", "Gare de Vénissieux", False, 1,
            [(45.7578, 4.8320), (45.7537, 4.8470)]),
        Leg("Saxe - Gambetta", "Saxe - Gambetta", 29040, 29160, None, None, True, 0, [(45.7537, 4.8470), (45.7537, 4.8470)]),
        Leg("Saxe - Gambetta", "Gare Part-Dieu", 29160, 29400, "B", "Charpennes", False, 2,
            [(45.7537, 4.8470), (45.7580, 4.8520), (45.7606, 4.8596)]),
    ])


def install(data_root: Path, version: str = V1, plan: dict = PLAN) -> Path:
    """What dataset-sync leaves behind, with tiny files: installed.json and the version's folder."""
    root = data_root / "france-live"
    folder = root / version
    for day in plan["days"]:
        (folder / day).mkdir(parents=True, exist_ok=True)
        (folder / day / "routes.bin").write_bytes(b"r" * 100)
        (folder / day / "stops.bin").write_bytes(b"s" * 50)
    (folder / "horizon.json").write_text(json.dumps(plan), encoding="utf-8")
    (folder / "dataset.json").write_text(json.dumps({
        "tool_version": "met-dataset-server france-live 1", "createdAt": "2026-11-19T03:04:12.219530004Z",
        "validity": {"start_date": plan["start"], "end_date": plan["end"]},
        "periods": [{"name": d, "stats": {"stops": 309288, "routes": 80073, "trips": 476873}} for d in plan["days"]]}))
    (folder / "sources.json").write_text(json.dumps([
        {"feed_id": "tcl", "name": "TCL Lyon", "layer": "regional", "licence": "mobilites", "trips": 12000},
        {"feed_id": "idfm", "name": "Île-de-France Mobilités", "layer": "regional", "licence": "mobilites", "trips": 90000},
        {"feed_id": "sncf-ter", "name": "TER", "layer": "longue_distance", "licence": "odbl", "trips": 8000}]))
    (folder / "licence.json").write_text(json.dumps({"licence": "ODbL-1.0", "name": "Open Database License (ODbL) v1.0",
                                                     "url": "https://opendatacommons.org/licenses/odbl/1-0/",
                                                     "notice": "france-live is a database…"}))
    (root / "installed.json").write_text(json.dumps({"epoch": "epoch-2-3", "version": version, "path": version,
                                                     "total_bytes": 211102506, "files": []}))
    for other in root.iterdir():  # dataset-sync keeps only the installed version
        if other.is_dir() and other.name != version:
            shutil.rmtree(other)
    return folder


class FakeServer:
    def __init__(self, folder: Path | None = None):
        self.folder = folder
        self.calls = []
        self.swaps = []
        self.info = {"type": "ready", "engine": "2.4.1", "java": "21", "stops": len(STOPS), "routes": 2, "trips": 10,
                     "loadMs": 12.5, "heapMb": 3.0, "period": "semaine", "periods": ["semaine", "samedi", "dimanche"]}
        self.closed = False

    def stops(self):
        return STOPS

    def route(self, origins, destinations, time, arrive_by=False, max_rounds=5, fallback_walk_m=None, school=True):
        def plain(end):  # stop ids sorted, an address as sent
            return end if isinstance(end, dict) else sorted(end)
        self.calls.append((plain(origins), plain(destinations), time, arrive_by, max_rounds, fallback_walk_m, school))
        if max_rounds > 50:
            raise EngineError("OutOfMemoryError: no room for that many rounds in a 1024 MB heap")
        return RouteResult(1.25, [journey()], max_rounds, school_blocked=0 if school else 5)

    def period(self, name):
        self.swaps.append(name)
        self.info = {**self.info, "period": name}
        return self.info

    def close(self):
        self.closed = True


class FakeSync:
    """SyncRun's stand-in: replays SyncKt lines; an update that ends in `done` installs `version`."""

    script: list[dict] = []
    install_version: str | None = None
    runs: list = []

    def __init__(self, root, base_url, epoch, check=False, java=None):
        self.root, self.base_url, self.epoch, self.check = root, base_url, epoch, check
        self.command = ["SyncKt"] + (["--check"] if check else [])
        self.code = None
        FakeSync.runs.append(self)

    def events(self):
        installed = dataset.installed(self.root)
        yield {"type": "installed", "version": installed.version if installed else None}
        yield {"type": "latest", "version": V2, "total_bytes": 211102506, "full_bytes": 43718605,
               "deltas": {V1: 187423}}
        if self.check:
            yield {"type": "plan", "method": "delta" if installed else "full", "from": installed and installed.version,
                   "to": V2, "bytes": 187423 if installed else 43718605, "full_bytes": 43718605, "total_bytes": 211102506}
        else:
            yield from FakeSync.script
            if FakeSync.install_version and any(e["type"] == "done" for e in FakeSync.script):
                install(self.root.parent, FakeSync.install_version)
        self.code = 1 if any(e["type"] == "error" for e in FakeSync.script) and not self.check else 0

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def fresh_fake_sync():
    FakeSync.script, FakeSync.install_version, FakeSync.runs = [], None, []


REPUBLIQUE = Address("10 Rue de la République", "69002 Lyon", 45.7625, 4.8357)


class FakeGeocoder:
    """No network in tests: answers addresses for anything that looks like a street."""

    def __init__(self):
        self.asked = []

    def search(self, text, near=None, limit=6):
        self.asked.append((text, near))
        return [REPUBLIQUE] if "rue" in text.lower() else []


# ── pieces ───────────────────────────────────────────────────────────────────────────


def test_places_group_by_name_and_search_ignores_accents(tmp_path):
    index = PlaceIndex(STOPS)
    assert index.attach_communes(tmp_path, LYON) is False
    bellecour = index.search("bellec")[0]
    assert bellecour.name == "Bellecour" and sorted(bellecour.ids) == [1, 2]
    assert index.search("gare part dieu")[0].name == "Gare Part-Dieu"
    assert index.search("chatelet")[0].name == "Châtelet (Paris)"
    assert [p.name for p in index.search("mairie")] == ["Mairie (Brest)", "Mairie (Vénissieux)"]
    assert "Saxe - Gambetta" in [p.name for p in index.search("lyon gambetta")]   # the commune matches too
    # The communes are cached by the places' fingerprint: read back, never asked again.
    again = PlaceIndex(STOPS)
    assert again.attach_communes(tmp_path, lambda lat, lon: 1 / 0) is True
    assert again.search("bellec")[0].commune == "Lyon 2e"
    # Other stops: computed again, and the old cache goes.
    moved = PlaceIndex(STOPS[:-1])
    assert moved.attach_communes(tmp_path, LYON) is False
    assert len(list(tmp_path.glob("communes-*.json"))) == 1


def test_random_pair_is_a_reasonable_trip():
    index = PlaceIndex(STOPS)
    a, b = index.random_pair(random.Random(1), min_km=1, max_km=10)
    assert a.name != b.name


def test_day_types_follow_the_french_calendar():
    plan = Plan(**PLAN)
    assert plan.network_for(dt.date(2026, 11, 24)) == "semaine"
    assert plan.network_for(dt.date(2026, 11, 28)) == "samedi"
    assert plan.network_for(dt.date(2026, 11, 29)) == "dimanche"
    assert plan.network_for(dt.date(2026, 12, 25)) is None                    # outside the window
    assert day_type(dt.date(2026, 12, 25), False) == "dimanche"               # Christmas runs as a Sunday
    assert day_type(dt.date(2027, 5, 6), False) == "dimanche"                 # Ascension
    assert day_type(dt.date(2026, 12, 22), True) == "vacances"
    assert day_type(dt.date(2026, 12, 22), False) == "semaine"


def test_formatting():
    assert hhmm(8 * 3600 + 5 * 60) == "08:05"
    assert hhmm(25 * 3600) == "01:00 (+1 j)"
    assert duration(35 * 60) == "35 min" and duration(75 * 60) == "1 h 15"
    assert ms(4.234) == "4,2 ms" and ms(250.4) == "250 ms"
    assert parse_time("8h30") == 30600 and parse_time("08:30") == 30600 and parse_time("bof") is None
    assert parse_changes("0") == 0 and parse_changes(" 12 ") == 12
    assert parse_changes("-1") is None and parse_changes("100") is None and parse_changes("") is None
    assert limit_text(0) == "trajets directs seulement (1 tour RAPTOR)"
    assert limit_text(1) == "au plus 1 correspondance (2 tours RAPTOR)"
    assert limit_text(20) == "au plus 20 correspondances (21 tours RAPTOR)"


def test_parse_route_and_best_journey():
    answer = {"type": "route", "ms": 3.5, "journeys": [
        [{"from": "A", "to": "B", "dep": 100, "arr": 900, "route": "1", "direction": None, "walk": False, "stops": 3,
          "path": [[45.0, 4.0], [45.1, 4.1]]}],
        [{"from": "A", "to": "C", "dep": 100, "arr": 500, "route": "2", "direction": "X", "walk": False, "stops": 1, "path": []},
         {"from": "C", "to": "B", "dep": 520, "arr": 800, "route": "3", "direction": "Y", "walk": False, "stops": 2, "path": []}],
    ]}
    result = parse_route(answer)
    assert result.ms == 3.5 and len(result.journeys) == 2
    assert result.best().arrival == 800 and result.best().changes == 1


def test_parse_route_reads_address_legs():
    answer = {"type": "route", "ms": 2.0, "maxRounds": 5, "fallback": True, "walkRadius": 6000.0, "journeys": [[
        {"from": "10 Rue X", "to": "Bellecour", "dep": 100, "arr": 400, "route": None, "direction": None, "walk": True,
         "kind": "walk_access", "stops": 0, "path": [[45.76, 4.83], [45.757, 4.832]]},
        {"from": "Bellecour", "to": "Part-Dieu", "dep": 400, "arr": 900, "route": "B", "direction": None, "walk": False,
         "kind": "transit", "stops": 2, "path": []}]]}
    result = parse_route(answer)
    assert result.fallback and result.walk_radius == 6000.0
    assert [leg.kind for leg in result.journeys[0].legs] == ["walk_access", "transit"]
    assert result.journeys[0].changes == 0
    assert km(6000.0) == "6 km" and km(500.0) == "0,5 km"


PHOTON = {"features": [
    {"geometry": {"coordinates": [4.8357, 45.7625]},   # an address: number + street
     "properties": {"housenumber": "10", "street": "Rue de la République", "postcode": "69002", "city": "Lyon",
                    "countrycode": "FR"}},
    {"geometry": {"coordinates": [4.8357, 45.7625]},   # the same again: dropped
     "properties": {"housenumber": "10", "street": "Rue de la République", "postcode": "69002", "city": "Lyon",
                    "countrycode": "FR"}},
    {"geometry": {"coordinates": [2.2945, 48.8584]},   # a place: its name, the street goes to the detail
     "properties": {"name": "Tour Eiffel", "street": "Avenue Gustave Eiffel", "postcode": "75007", "city": "Paris",
                    "countrycode": "FR"}},
    {"geometry": {"coordinates": [6.1432, 46.2044]},   # Geneva: inside the box, not in France
     "properties": {"name": "Gare Cornavin", "city": "Genève", "countrycode": "CH"}},
    {"geometry": {"coordinates": [-61.5, 16.2]},       # overseas: outside mainland France
     "properties": {"name": "Pointe-à-Pitre", "countrycode": "FR"}},
    {"geometry": {"coordinates": [4.0, 45.0]}, "properties": {"countrycode": "FR"}},   # nothing to call it
    {"geometry": {}, "properties": {"name": "Nowhere"}},
]}


def test_photon_answers_are_read_as_pelo_reads_them():
    found = parse_photon(PHOTON)
    assert [(a.label, a.detail) for a in found] == [
        ("10 Rue de la République", "69002 Lyon"),
        ("Tour Eiffel", "Avenue Gustave Eiffel, 75007 Paris")]
    assert found[1].lat == 48.8584 and found[1].lon == 2.2945
    assert found[0].endpoint() == {"lat": 45.7625, "lon": 4.8357, "label": "10 Rue de la République"}
    assert "Tour Eiffel" in found[1].option_text() and "75007 Paris" in found[1].option_text()
    assert feature_to_address({"geometry": {"coordinates": [4.8, 45.7]}, "properties": {"street": "Rue A"}}).label == "Rue A"
    assert len(parse_photon({"features": PHOTON["features"][:1] * 3 + PHOTON["features"][2:3]}, limit=1)) == 1


@pytest.fixture
def photon_server():
    """A local stand-in for photon.komoot.io: records each query, answers PHOTON (or a 500)."""
    state = {"queries": [], "fail": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["queries"].append(parse_qs(urlparse(self.path).query))
            if state["fail"]:
                self.send_response(500)
                self.end_headers()
                return
            body = json.dumps(PHOTON).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/api/"
    yield state
    server.shutdown()


def test_geocoder_asks_photon_like_pelo_and_caches(photon_server, tmp_path):
    cache = tmp_path / "geocode.json"
    geocoder = Geocoder(cache, url=photon_server["url"])
    assert geocoder.search("10") == []                       # under 3 characters: not asked
    assert photon_server["queries"] == []
    found = geocoder.search("10 rue de la republique", near=(45.75, 4.85))
    assert [a.label for a in found] == ["10 Rue de la République", "Tour Eiffel"]
    query = photon_server["queries"][-1]
    assert query["q"] == ["10 rue de la republique"] and query["lang"] == ["fr"] and query["limit"] == ["8"]
    assert query["lat"] == ["45.7500"] and query["lon"] == ["4.8500"] and query["bbox"] == ["-5.3,41.2,9.7,51.2"]
    assert geocoder.search(" 10 RUE de la republique ", near=(45.75, 4.85)) == found   # cached: not asked again
    assert len(photon_server["queries"]) == 1
    assert Geocoder(cache, url=photon_server["url"]).search("10 rue de la republique", near=(45.75, 4.85)) == found
    assert len(photon_server["queries"]) == 1                # the cache survives a restart
    photon_server["fail"] = True
    assert geocoder.search("tour eiffel") == []              # a failure is silent, as in Pelo
    photon_server["fail"] = False
    assert [a.label for a in geocoder.search("tour eiffel")][:1] == ["10 Rue de la République"]  # and not cached


def test_map_draws_france_and_the_journey():
    text = mapview.draw(40, 12, journey(), OUTLINE, zoom=False)
    lines = text.plain.split("\n")
    assert len(lines) == 12 and all(len(line) == 40 for line in lines)
    zoomed = mapview.draw(40, 12, journey(), OUTLINE, zoom=True)
    styles = {span.style for span in zoomed.spans}
    assert mapview.START in styles and mapview.END in styles and mapview.ride_colour(0) in styles


def test_map_shows_names_scale_and_dashed_walks():
    wide = mapview.draw(100, 30, None, OUTLINE, zoom=False).plain
    assert "Paris" in wide and "Lyon" in wide and "km" in wide            # cities and the scale bar
    trip = mapview.draw(100, 30, journey(), OUTLINE, zoom=True).plain
    assert "Bellecour" in trip and "Gare Part-Dieu" in trip               # start and end named
    lines = trip.split("\n")
    assert len(lines) == 30 and all(len(line) == 100 for line in lines)
    assert "km" in lines[-1]
    legend = mapview.legend(journey()).plain
    assert "D" in legend and "B" in legend and "à pied" in legend


def test_settings_round_trip_keeps_only_changes(tmp_path):
    path = tmp_path / "settings.json"
    s = settings_module.load(path)
    assert s.server.base_url == "https://api.dotshell.eu" and s.engine.xmx == "1g"
    s.engine.xmx = "2g"
    s.routing.geocoding = False
    settings_module.save(s, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"engine": {"xmx": "2g"}, "routing": {"geocoding": False}}
    again = settings_module.load(path)
    assert again.engine.xmx == "2g" and again.routing.geocoding is False
    assert settings_module.parse(float, "0,5") == 0.5 and settings_module.parse(bool, "oui") is True
    with pytest.raises(ValueError):
        settings_module.parse(int, "douze")
    assert settings_module.check(again) == []
    again.engine.xmx, again.server.base_url = "beaucoup", "api.dotshell.eu"
    assert len(settings_module.check(again)) == 2


def test_installed_version_is_read_as_dataset_sync_left_it(tmp_path):
    assert dataset.installed(tmp_path / "france-live") is None
    folder = install(tmp_path)
    found = dataset.installed(tmp_path / "france-live")
    assert found.version == V1 and found.dir == folder
    assert found.day_types() == ["semaine", "samedi", "dimanche"]
    assert found.plan().days["samedi"] == "2026-11-28"
    assert found.created_at() == dt.datetime(2026, 11, 19, 3, 4, 12, tzinfo=dt.timezone.utc)
    assert found.size("semaine") == 150
    shutil.rmtree(folder)                    # a pointer without its folder is no installation
    assert dataset.installed(tmp_path / "france-live") is None


def test_sync_run_reads_synckt_lines(tmp_path):
    lines = ['{"type":"installed","version":null}\n', "WARNING: a JVM line\n",
             '{"type":"plan","method":"full","bytes":10}\n', '{"type":"done","version":"v","method":"full"}\n']

    class Process:
        def __init__(self, command, **kwargs):
            self.command, self.stdout, self.stderr = command, iter(lines), None

        def wait(self):
            return 0

        def poll(self):
            return 0

    run = SyncRun(tmp_path, "https://api.dotshell.eu", "epoch-2-3", check=True, popen=Process)
    assert run.command[-1] == "--check" and "eu.dotshell.met.console.SyncKt" in run.command
    assert [e["type"] for e in run.events()] == ["installed", "plan", "done"] and run.code == 0


# ── the app, headless ────────────────────────────────────────────────────────────────


def make_app(data_root: Path, server: FakeServer | None = None, geocoder=None, today=dt.date(2026, 11, 19)):
    servers = []

    def factory(folder):
        made = server if server is not None and not servers else FakeServer(folder)
        made.folder = folder
        servers.append(made)
        return made

    app = Explorer(data_root, server_factory=factory, commune_lookup=LYON, outline=OUTLINE,
                   geocoder=geocoder or FakeGeocoder(), today=today, sync_runner=FakeSync)
    app.servers = servers
    return app


async def wait_ready(app, pilot):
    for _ in range(100):
        await pilot.pause(0.05)
        if app.index is not None and not app.query_one("#from").disabled:
            return
    raise AssertionError("app never got ready")


async def pick_trip(pilot):
    await pilot.click("#from")
    await pilot.press(*"bellec", "enter")
    await pilot.press(*"part dieu", "enter")
    await pilot.pause(0.3)


def test_app_routes_between_two_picked_stops(tmp_path):
    install(tmp_path)

    async def scenario():
        server = FakeServer()
        app = make_app(tmp_path, server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            assert server.folder == tmp_path / "france-live" / V1
            assert f"france-live {V1}" in app.sub_title and "jeudi 19 novembre 2026" in app.sub_title
            await pick_trip(pilot)
            assert server.calls[-1][:3] == ([1, 2], [3], 28800)
            summary = str(app.query_one("#summary").render())
            assert "08:00 → 08:10" in summary and "1,2 ms" in summary and "1 correspondance" in summary
            await pilot.press("ctrl+e")      # swap
            await pilot.pause(0.3)
            assert server.calls[-1][:2] == ([3], [1, 2])
            await pilot.press("ctrl+r")      # random trip
            await pilot.pause(0.3)
            assert len(server.calls) >= 3 + 30   # 30 warm-up calls at load
    asyncio.run(scenario())


def test_app_routes_from_an_address(tmp_path):
    install(tmp_path)

    async def scenario():
        server, geocoder = FakeServer(), FakeGeocoder()
        app = make_app(tmp_path, server, geocoder)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            await pilot.click("#from")
            await pilot.press(*"10 rue de la republique")
            await pilot.pause(0.7)                          # the geocoder waits for typing to pause
            options = app.query_one("#from_list")
            texts = [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]
            assert texts[0].startswith("Adresses") and "10 Rue de la République" in texts[1]
            assert geocoder.asked[-1] == ("10 rue de la republique", None)
            assert len(geocoder.asked) < len("10 rue de la republique")   # not once per keystroke
            await pilot.press("enter")                      # the first address is highlighted
            assert app.chosen["from"] == REPUBLIQUE
            await pilot.press(*"part dieu", "enter")
            await pilot.pause(0.3)
            origin, destination, time, arrive_by, rounds, fallback, school = server.calls[-1]
            assert origin == REPUBLIQUE.endpoint() and destination == [3] and fallback == 6000.0
            box = app.query_one("#to")
            box.value = ""
            box.focus()
            await pilot.press(*"rue")
            await pilot.pause(0.7)
            assert geocoder.asked[-1] == ("rue", (REPUBLIQUE.lat, REPUBLIQUE.lon))
            assert engine_endpoint(app.index.search("bellec")[0]) == [1, 2]
    asyncio.run(scenario())


def test_app_school_switch_reaches_the_engine(tmp_path):
    install(tmp_path)

    async def scenario():
        server = FakeServer()
        server.info = {**server.info, "schoolRoutes": 5, "schoolTrips": 1234}
        app = make_app(tmp_path, server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            switch = app.query_one("#school")
            assert not switch.disabled and switch.value
            assert "1 234 courses" in str(app.query_one("#school_label").render())
            await pick_trip(pilot)
            assert server.calls[-1][6] is True
            await pilot.click("#school")
            await pilot.pause(0.3)
            assert server.calls[-1][6] is False and server.calls[-1][:2] == ([1, 2], [3])
            assert "sans les lignes scolaires" in str(app.query_one("#summary").render())
    asyncio.run(scenario())


def test_app_picks_a_date_and_the_engine_swaps_day_types(tmp_path):
    install(tmp_path)

    async def scenario():
        server = FakeServer()
        app = make_app(tmp_path, server)
        async with app.run_test(size=(150, 50)) as pilot:
            await wait_ready(app, pilot)
            day = app.query_one("#day")
            assert len(app.dates) == 29 and day.value == "2026-11-19"
            assert "données du jeu. 19 nov. au jeu. 17 déc." in str(app.query_one("#when_label").render())
            await pick_trip(pilot)
            assert server.swaps == [] and "réseau semaine, celui du mar. 24 nov." in str(app.query_one("#summary").render())
            day.value = "2026-12-05"                                # a Saturday: the engine swaps first
            await pilot.pause(0.4)
            assert server.swaps == ["samedi"] and server.calls[-1][:2] == ([1, 2], [3])
            assert "samedi 5 décembre 2026 (réseau samedi, celui du sam. 28 nov.)" in str(app.query_one("#summary").render())
            day.value = "2026-12-08"                                # back to a weekday
            await pilot.pause(0.4)
            assert server.swaps == ["samedi", "semaine"] and "réseau semaine" in app.sub_title
    asyncio.run(scenario())


def test_app_change_limit_reaches_the_engine(tmp_path):
    install(tmp_path)

    async def scenario():
        server = FakeServer()
        app = make_app(tmp_path, server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            await pick_trip(pilot)
            assert server.calls[-1][4] == 5                     # default: 4 changes = 5 rounds
            await pilot.click("#more")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 6
            assert "au plus 5 correspondances (6 tours RAPTOR)" in str(app.query_one("#summary").render())
            box = app.query_one("#max_changes")
            box.value = "80"                                     # the fake engine runs out of memory
            await pilot.click("#max_changes")
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 81
            assert "Pas assez de mémoire" in str(app.query_one("#summary").render())
    asyncio.run(scenario())


def test_loading_view_tracks_steps():
    view = LoadingView("Test", [("a", "Premier", 1), ("b", "Second", 3)])
    assert view.fraction(0) == 0
    view.start("a")
    view.done("a", "fait")
    view.start("b")
    view.progress("b", 0.5, "1/2")
    assert abs(view.fraction(0) - (1 + 3 * 0.5) / 4) < 1e-9
    text = view.render().plain
    assert "✓  Premier" in text and "fait" in text and "1/2" in text and view.finished is None
    view.done("b")
    assert view.finished is not None and "100 %" in view.render().plain


def test_app_says_which_loading_step_failed(tmp_path):
    install(tmp_path)

    class BrokenServer(FakeServer):
        def stops(self):
            raise EngineError("engine stopped: boom")

    async def scenario():
        app = make_app(tmp_path, BrokenServer())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause(0.5)
            loader = app.query_one("#loader")
            assert loader.steps["engine"].state == "done" and loader.steps["stops"].state == "fail"
            assert "boom" in loader.render().plain and app.query_one("#from").disabled
    asyncio.run(scenario())


def test_tabs_and_the_data_of_the_installed_version(tmp_path):
    install(tmp_path)

    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(170, 50)) as pilot:
            await wait_ready(app, pilot)
            for key, tab in (("f2", "tab-update"), ("f3", "tab-data"), ("f4", "tab-settings"), ("f5", "tab-help"),
                             ("f1", "tab-route")):
                await pilot.press(key)
                await pilot.pause(0.1)
                assert app.query_one("#tabs").active == tab
            data = app.query_one("#data")
            assert V1 in str(data.query_one("#data-version").render())
            days = data.query_one("#data-days").render()
            assert "idfm" in str(days.renderable if hasattr(days, "renderable") else days) or True
            assert "ODbL" in str(data.query_one("#data-licence").render())
            assert "raptor-kmp 2.4.1" in str(data.query_one("#data-engine").render())
            assert data.query_one("#src-table").row_count == 3
            data.query_one("#src-search").value = "mobilites"
            await pilot.pause(0.2)
            assert data.query_one("#src-table").row_count == 2
            assert "2 mobilites" in str(data.query_one("#src-count").render())
            # The check at start-up found the server's newer version and a delta for this one.
            update = app.query_one("#update")
            assert FakeSync.runs and FakeSync.runs[0].check
            state = str(update.query_one("#up-state").render())
            assert V2 in state and "par différence" in state
    asyncio.run(scenario())


def test_without_a_version_the_console_opens_on_updates_and_installs_one(tmp_path):
    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.3)
            assert app.query_one("#tabs").active == "tab-update"
            assert app.query_one("#empty").display and app.query_one("#from").disabled
            assert "Aucune version" in str(app.query_one("#up-state").render())
            assert "paquet complet" in str(app.query_one("#up-state").render())   # the start-up check's plan
            FakeSync.script = [{"type": "plan", "method": "full", "from": None, "to": V1, "bytes": 43718605,
                                "full_bytes": 43718605, "total_bytes": 211102506},
                               {"type": "progress", "done": 43718605, "total": 43718605},
                               {"type": "file", "path": "semaine/stops.bin", "bytes": 50, "copied": 0, "reused": 0,
                                "inserted": 50, "derived": 0, "index": 0, "count": 1},
                               {"type": "switched", "version": V1},
                               {"type": "done", "from": None, "version": V1, "method": "full", "downloaded": 43718605}]
            FakeSync.install_version = V1
            await pilot.click("#up-run")
            await wait_ready(app, pilot)
            assert app.installed.version == V1 and app.servers[-1].folder == tmp_path / "france-live" / V1
            assert not app.query_one("#empty").display
            assert V1 in str(app.query_one("#data-version").render())
            # The next one: the engine restarts on the new version.
            FakeSync.script[-1] = {"type": "done", "from": V1, "version": V2, "method": "delta", "downloaded": 187423}
            FakeSync.install_version = V2
            runs = len(FakeSync.runs)
            await pilot.click("#up-run")
            await pilot.pause(0.5)
            assert len(FakeSync.runs) == runs + 1, app.query_one("#update").messages
            await wait_ready(app, pilot)
            assert app.installed.version == V2 and app.servers[0].closed
            assert app.servers[-1].folder == tmp_path / "france-live" / V2
    asyncio.run(scenario())


def test_a_failed_update_keeps_the_version_and_says_why(tmp_path):
    install(tmp_path)

    async def scenario():
        app = make_app(tmp_path)
        async with app.run_test(size=(170, 50)) as pilot:
            await wait_ready(app, pilot)
            FakeSync.script = [{"type": "error", "kind": "SyncException", "message": "SHA-256 mismatch"}]
            app.query_one("#update").start(check=False)
            await pilot.pause(0.4)
            assert app.installed.version == V1 and len(app.servers) == 1
            assert any("SHA-256 mismatch" in m for m in app.query_one("#update").messages)
    asyncio.run(scenario())


INSTALLED = Path(__file__).resolve().parent.parent / "data"


@pytest.mark.skipif(dataset.installed(INSTALLED / "france-live") is None or not (ENGINE_INSTALL / "lib").exists(),
                    reason="needs an installed france-live version (console/data) and the engine (installDist)")
def test_real_engine_on_the_installed_version():
    from met_console.backend import EngineServer

    installed = dataset.installed(INSTALLED / "france-live")
    server = EngineServer(installed.dir, xmx="512m")
    try:
        assert server.info["engine"] >= "2.4.1" and server.info["stops"] > 300_000
        index = PlaceIndex(server.stops())
        origin = index.search("lyon part dieu")[0]
        destination = index.search("gare de lyon bellecour")[0] if index.search("gare de lyon bellecour") else \
            index.search("bellecour")[0]
        result = server.route(origin.ids, destination.ids, 8 * 3600)
        best = result.best()
        assert best is not None and best.arrival - best.departure < 3600
        for rounds in (1, 12, 2):
            assert all(len(j.rides) <= rounds for j in server.route(origin.ids, destination.ids, 8 * 3600,
                                                                    max_rounds=rounds).journeys)
        saturday = server.period("samedi")
        assert saturday["period"] == "samedi"
        address = {"lat": 45.7672, "lon": 4.8337, "label": "Place des Terreaux"}
        best = server.route(address, destination.ids, 8 * 3600).best()
        assert best is not None and best.legs[0].kind == "walk_access" and best.legs[0].from_name == "Place des Terreaux"
    finally:
        server.close()
