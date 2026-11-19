"""The terminal explorer: search, map, formatting, and the app driven headless."""

import asyncio
import datetime as dt
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from gtfs_bench.explorer import mapview
from gtfs_bench.explorer.app import Explorer, duration, engine_endpoint, hhmm, km, limit_text, ms, parse_changes, parse_time
from gtfs_bench.explorer.backend import EngineError, Journey, Leg, RouteResult, parse_route
from gtfs_bench.explorer.geocode import Address, Geocoder, feature_to_address, parse_photon
from gtfs_bench.explorer.loading import LoadingView
from gtfs_bench.explorer.places import PlaceIndex

STOPS = [
    (1, "Bellecour", 45.7578, 4.8320), (2, "Bellecour", 45.7581, 4.8326), (3, "Gare Part-Dieu", 45.7606, 4.8596),
    (4, "Saxe - Gambetta", 45.7537, 4.8470), (5, "Mairie (Vénissieux)", 45.6970, 4.8870),
    (6, "Mairie (Brest)", 48.3900, -4.4860), (7, "Châtelet (Paris)", 48.8584, 2.3470),
]
LYON = lambda lat, lon: ["Lyon 2e Arrondissement" if la < 45.759 and lo < 4.84 else "Lyon 3e" if la > 45.70 else "Vénissieux"
                         for la, lo in zip(lat, lon)]


def journey():
    return Journey([
        Leg("Bellecour", "Saxe - Gambetta", 28800, 29040, "D", "Gare de Vénissieux", False, 1,
            [(45.7578, 4.8320), (45.7537, 4.8470)]),
        Leg("Saxe - Gambetta", "Saxe - Gambetta", 29040, 29160, None, None, True, 0, [(45.7537, 4.8470), (45.7537, 4.8470)]),
        Leg("Saxe - Gambetta", "Gare Part-Dieu", 29160, 29400, "B", "Charpennes", False, 2,
            [(45.7537, 4.8470), (45.7580, 4.8520), (45.7606, 4.8596)]),
    ])


class FakeServer:
    info = {"type": "ready", "stops": len(STOPS), "routes": 2, "trips": 10, "loadMs": 12.5, "heapMb": 3.0}

    def __init__(self):
        self.calls = []

    def stops(self):
        return STOPS

    def route(self, origins, destinations, time, arrive_by=False, max_rounds=5, fallback_walk_m=None, school=True):
        def plain(end):  # stop ids sorted, an address as sent
            return end if isinstance(end, dict) else sorted(end)
        self.calls.append((plain(origins), plain(destinations), time, arrive_by, max_rounds, fallback_walk_m, school))
        if max_rounds > 50:
            raise EngineError("OutOfMemoryError: no room for that many rounds in a 1024 MB heap")
        return RouteResult(1.25, [journey()], max_rounds, school_blocked=0 if school else 5)

    def close(self):
        pass


REPUBLIQUE = Address("10 Rue de la République", "69002 Lyon", 45.7625, 4.8357)


class FakeGeocoder:
    """No network in tests: answers addresses for anything that looks like a street."""

    def __init__(self):
        self.asked = []

    def search(self, text, near=None, limit=6):
        self.asked.append((text, near))
        return [REPUBLIQUE] if "rue" in text.lower() else []


# ── pieces ───────────────────────────────────────────────────────────────────────────


def test_places_group_by_name_and_search_ignores_accents():
    index = PlaceIndex(STOPS)
    index.attach_communes(lookup=LYON)
    bellecour = index.search("bellec")[0]
    assert bellecour.name == "Bellecour" and sorted(bellecour.ids) == [1, 2]
    assert index.search("gare part dieu")[0].name == "Gare Part-Dieu"
    assert index.search("chatelet")[0].name == "Châtelet (Paris)"
    assert [p.name for p in index.search("mairie")] == ["Mairie (Brest)", "Mairie (Vénissieux)"]
    assert index.search("x") == [] or all("x" in p.key for p in index.search("x"))


def test_search_matches_the_commune_too():
    index = PlaceIndex(STOPS)
    index.attach_communes(lookup=LYON)
    assert "Saxe - Gambetta" in [p.name for p in index.search("lyon gambetta")]


def test_random_pair_is_a_reasonable_trip():
    index = PlaceIndex(STOPS)
    a, b = index.random_pair(random.Random(1), min_km=1, max_km=10)
    assert a.name != b.name


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
    outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
    text = mapview.draw(40, 12, journey(), outline, zoom=False)
    lines = text.plain.split("\n")
    assert len(lines) == 12 and all(len(line) == 40 for line in lines)
    zoomed = mapview.draw(40, 12, journey(), outline, zoom=True)
    styles = {span.style for span in zoomed.spans}
    assert mapview.START in styles and mapview.END in styles and mapview.ride_colour(0) in styles


# ── the app, headless ────────────────────────────────────────────────────────────────


def make_app(server, geocoder=None):
    outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
    return Explorer(Path("."), "Test", server=server, commune_lookup=LYON, outline=outline,
                    reference_day=dt.date(2026, 11, 24), geocoder=geocoder or FakeGeocoder())


async def wait_ready(app, pilot):
    for _ in range(100):
        await pilot.pause(0.05)
        if app.index is not None and not app.query_one("#from").disabled:
            return
    raise AssertionError("app never got ready")


def test_app_routes_between_two_picked_stops():
    async def scenario():
        server = FakeServer()
        app = make_app(server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            assert "mardi 24 novembre 2026" in app.sub_title
            await pilot.click("#from")
            await pilot.press(*"bellec", "enter")
            await pilot.press(*"part dieu", "enter")
            await pilot.pause(0.3)
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


def test_app_routes_from_an_address():
    async def scenario():
        server, geocoder = FakeServer(), FakeGeocoder()
        app = make_app(server, geocoder)
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
            # Typing the other end leans the search towards the address already chosen.
            box = app.query_one("#to")
            box.value = ""
            box.focus()
            await pilot.press(*"rue")
            await pilot.pause(0.7)
            assert geocoder.asked[-1] == ("rue", (REPUBLIQUE.lat, REPUBLIQUE.lon))
            # A stop still goes to the engine as its ids.
            assert engine_endpoint(app.index.search("bellec")[0]) == [1, 2]
    asyncio.run(scenario())


def test_app_school_switch_reaches_the_engine():
    class SchoolServer(FakeServer):
        info = {**FakeServer.info, "schoolRoutes": 5, "schoolTrips": 1234}

    async def scenario():
        server = SchoolServer()
        app = make_app(server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            switch = app.query_one("#school")
            assert not switch.disabled and switch.value
            assert "1 234 courses" in str(app.query_one("#school_label").render())
            await pilot.click("#from")
            await pilot.press(*"bellec", "enter")
            await pilot.press(*"part dieu", "enter")
            await pilot.pause(0.3)
            assert server.calls[-1][6] is True                     # school lines in by default
            await pilot.click("#school")                           # off: searched again without them
            await pilot.pause(0.3)
            assert server.calls[-1][6] is False and server.calls[-1][:2] == ([1, 2], [3])
            assert "sans les lignes scolaires" in str(app.query_one("#summary").render())
            assert "¬scol" in str(app.query_one("#history").render())
    asyncio.run(scenario())


def test_app_picks_a_date_and_the_engine_swaps_day_types():
    from gtfs_bench.horizon import Plan

    class LiveServer(FakeServer):
        def __init__(self):
            super().__init__()
            self.info = {**FakeServer.info, "period": "semaine", "periods": ["semaine", "samedi", "dimanche"]}
            self.swaps = []

        def period(self, name):
            self.swaps.append(name)
            self.info = {**self.info, "period": name}
            return self.info

    plan = Plan(computed_on="2026-11-19", start="2026-11-19", end="2026-12-17", binding_feed="idfm", binding_share=0.27,
                days={"semaine": "2026-11-24", "samedi": "2026-11-28", "dimanche": "2026-11-29"})

    async def scenario():
        server = LiveServer()
        outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
        app = Explorer(Path("."), "Live", server=server, commune_lookup=LYON, outline=outline, geocoder=FakeGeocoder(),
                       plan=plan, today=dt.date(2026, 11, 19))
        async with app.run_test(size=(150, 50)) as pilot:
            await wait_ready(app, pilot)
            day = app.query_one("#day")
            assert len(app.dates) == 29 and day.value == "2026-11-19"
            assert "données du jeu. 19 nov. au jeu. 17 déc." in str(app.query_one("#when_label").render())
            await pilot.click("#from")
            await pilot.press(*"bellec", "enter")
            await pilot.press(*"part dieu", "enter")
            await pilot.pause(0.3)
            assert server.swaps == [] and "réseau semaine, celui du mar. 24 nov." in str(app.query_one("#summary").render())
            day.value = "2026-12-05"                                # a Saturday: the engine swaps first
            await pilot.pause(0.4)
            assert server.swaps == ["samedi"] and server.calls[-1][:2] == ([1, 2], [3])
            assert "samedi 5 décembre 2026 (réseau samedi, celui du sam. 28 nov.)" in str(app.query_one("#summary").render())
            day.value = "2026-12-08"                                # back to a weekday
            await pilot.pause(0.4)
            assert server.swaps == ["samedi", "semaine"] and "réseau semaine" in app.sub_title
    asyncio.run(scenario())


def test_school_switch_is_off_limits_without_a_list():
    async def scenario():
        app = make_app(FakeServer())
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            assert app.query_one("#school").disabled
            assert "pas de liste" in str(app.query_one("#school_label").render())
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


def test_app_shows_the_checklist_then_the_map():
    async def scenario():
        app = make_app(FakeServer())
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            loader = app.query_one("#loader")
            assert all(step.state == "done" for step in loader.steps.values())
            assert "30/30" in loader.render().plain or "30 recherches" in loader.render().plain
            await pilot.pause(1.2)
            assert not loader.display and app.query_one("#map").display
    asyncio.run(scenario())


def test_app_says_which_loading_step_failed():
    class BrokenServer(FakeServer):
        def stops(self):
            raise EngineError("engine stopped: boom")

    async def scenario():
        app = make_app(BrokenServer())
        async with app.run_test(size=(150, 45)) as pilot:
            await pilot.pause(0.5)
            loader = app.query_one("#loader")
            assert loader.steps["engine"].state == "done" and loader.steps["stops"].state == "fail"
            assert "boom" in loader.render().plain and app.query_one("#from").disabled
    asyncio.run(scenario())


def test_app_change_limit_reaches_the_engine():
    async def scenario():
        server = FakeServer()
        app = make_app(server)
        async with app.run_test(size=(150, 45)) as pilot:
            await wait_ready(app, pilot)
            assert "mardi 24 novembre 2026" in str(app.query_one("#when_label").render())
            await pilot.click("#from")
            await pilot.press(*"bellec", "enter")
            await pilot.press(*"part dieu", "enter")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 5                     # default: 4 changes = 5 rounds
            await pilot.click("#more")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 6
            assert "au plus 5 correspondances (6 tours RAPTOR)" in str(app.query_one("#summary").render())
            assert "≤5" in str(app.query_one("#history").render())
            box = app.query_one("#max_changes")
            box.value = "0"
            await pilot.click("#max_changes")
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 1
            await pilot.click("#fewer")                          # already at 0: stays there
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 1 and box.value == "0"
            box.value = "80"                                     # the fake engine runs out of memory
            await pilot.click("#max_changes")
            await pilot.press("enter")
            await pilot.pause(0.3)
            assert server.calls[-1][4] == 81
            assert "Pas assez de mémoire" in str(app.query_one("#summary").render())
    asyncio.run(scenario())


ROOT = Path(__file__).resolve().parent.parent
LYON_DATA = ROOT / "data" / "raptor" / "metropole-lyon" / "bench"


@pytest.mark.skipif(not (LYON_DATA / "routes.bin").exists() or not (ROOT / "engine/build/install/benchmark-engine/lib").exists(),
                    reason="needs the converted Lyon tier and :benchmark-engine:installDist")
def test_real_engine_on_lyon():
    from gtfs_bench.explorer.backend import EngineServer

    server = EngineServer(LYON_DATA, xmx="256m")
    try:
        index = PlaceIndex(server.stops())
        origin, destination = index.search("bellecour")[0], index.search("gare part dieu")[0]
        result = server.route(origin.ids, destination.ids, 8 * 3600)
        best = result.best()
        assert best is not None and best.arrival - best.departure < 3600
        assert result.ms > 0 and all(leg.path for leg in best.legs)
        # The round limit holds, also after a bigger one (the engine caches its search state).
        far = index.search("vaulx en velin la soie")[0]
        for rounds in (1, 30, 2, 12, 1):
            result = server.route(origin.ids, far.ids, 8 * 3600, max_rounds=rounds)
            assert result.max_rounds == rounds
            assert all(len(j.rides) <= rounds for j in result.journeys)
        arrive_by = server.route(origin.ids, far.ids, 9 * 3600, arrive_by=True, max_rounds=20)
        assert arrive_by.max_rounds == 20 and all(j.arrival <= 9 * 3600 for j in arrive_by.journeys)
        # From an address (Hôtel de Ville square): a walk to a stop first, starting at the address.
        address = {"lat": 45.7672, "lon": 4.8337, "label": "Place des Terreaux"}
        result = server.route(address, destination.ids, 8 * 3600)
        best = result.best()
        assert best is not None and not result.fallback and result.walk_radius == 500.0
        assert best.legs[0].kind == "walk_access" and best.legs[0].from_name == "Place des Terreaux"
        assert best.legs[0].path[0] == (45.7672, 4.8337)
        # 1.5 km west of the westernmost stop, nothing within 500 m: the second try walks up to 6 km.
        west = min(server.stops(), key=lambda s: s[3])
        field = {"lat": west[2], "lon": west[3] - 0.02, "label": "Champ"}
        wide = server.route(field, destination.ids, 8 * 3600, fallback_walk_m=6000)
        assert wide.fallback and wide.walk_radius == 6000.0
        assert wide.journeys and wide.best().legs[0].kind == "walk_access"
    finally:
        server.close()
