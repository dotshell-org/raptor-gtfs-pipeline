"""The terminal explorer: search, map, formatting, and the app driven headless."""

import asyncio
import datetime as dt
import random
from pathlib import Path

import pytest

from gtfs_bench.explorer import mapview
from gtfs_bench.explorer.app import Explorer, duration, hhmm, ms, parse_time
from gtfs_bench.explorer.backend import Journey, Leg, RouteResult, parse_route
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

    def route(self, origins, destinations, time, arrive_by=False, max_rounds=5):
        self.calls.append((sorted(origins), sorted(destinations), time, arrive_by))
        return RouteResult(1.25, [journey()])

    def close(self):
        pass


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


def test_map_draws_france_and_the_journey():
    outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
    text = mapview.draw(40, 12, journey(), outline, zoom=False)
    lines = text.plain.split("\n")
    assert len(lines) == 12 and all(len(line) == 40 for line in lines)
    zoomed = mapview.draw(40, 12, journey(), outline, zoom=True)
    styles = {span.style for span in zoomed.spans}
    assert mapview.START in styles and mapview.END in styles and mapview.ride_colour(0) in styles


# ── the app, headless ────────────────────────────────────────────────────────────────


def make_app(server):
    outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
    return Explorer(Path("."), "Test", server=server, commune_lookup=LYON, outline=outline,
                    reference_day=dt.date(2026, 11, 24))


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
    finally:
        server.close()
