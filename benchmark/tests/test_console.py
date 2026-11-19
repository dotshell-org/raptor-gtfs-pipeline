"""The console's other tabs: settings, catalogue editing, networks, actions, and the map's extras."""

import asyncio
import csv
import json

import pytest

from gtfs_bench import settings as settings_module
from gtfs_bench.catalog import CATALOG_COLUMNS, read_catalog
from gtfs_bench.explorer import mapview, panes, tasks
from gtfs_bench.explorer.panes import check_row, scan_networks, write_catalog

from tests.test_explorer import FakeServer, journey, make_app, wait_ready


def test_settings_round_trip_keeps_only_changes(tmp_path):
    path = tmp_path / "settings.json"
    s = settings_module.load(path)
    assert s.merge.name_radius_m == 500.0 and s.reference_date() is None
    s.merge.name_radius_m = 350.0
    s.data.reference_date = "2026-12-01"
    settings_module.save(s, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"data": {"reference_date": "2026-12-01"},
                                                             "merge": {"name_radius_m": 350.0}}
    again = settings_module.load(path)
    assert again.merge.name_radius_m == 350.0 and again.reference_date().isoformat() == "2026-12-01"
    assert again.merge.transfer_params().radius_m == 300.0
    assert settings_module.parse(float, "0,5") == 0.5 and settings_module.parse(bool, "oui") is True
    with pytest.raises(ValueError):
        settings_module.parse(int, "douze")
    labels = [f[3] for f in settings_module.fields_of(again)]
    assert "Rayon des homonymes (m)" in labels and len(labels) > 20


def test_catalogue_rows_are_checked_and_written_with_a_backup(tmp_path):
    rows = [{c: "" for c in CATALOG_COLUMNS} | {"feed_id": "a", "include": True, "clip": False, "layer": "regional",
                                                 "priority": "10", "school": "^S\\d"},
            {c: "" for c in CATALOG_COLUMNS} | {"feed_id": "b", "include": False, "clip": True, "layer": "scolaire",
                                                 "priority": "90", "school": "all"}]
    assert check_row(rows[0]) == [] and check_row(rows[1]) == []
    assert check_row({**rows[0], "priority": "dix"}) == ["la priorité doit être un nombre"]
    assert "regex invalide" in check_row({**rows[0], "keep_routes": "(["})[0]
    path, backups = tmp_path / "catalog.csv", tmp_path / "backups"
    path.write_text("old", encoding="utf-8")
    backup = write_catalog(rows, path, backups)
    assert backup.read_text(encoding="utf-8") == "old"
    back = read_catalog(path)
    assert [r["include"] for r in back] == [True, False] and back[1]["clip"] is True and back[1]["school"] == "all"
    with path.open(encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == CATALOG_COLUMNS


def test_networks_are_found_with_their_numbers(tmp_path):
    tier = tmp_path / "metropole-lyon"
    (tier / "bench").mkdir(parents=True)
    (tier / "bench" / "routes.bin").write_bytes(b"x" * 1024)
    (tier / "bench" / "stops.bin").write_bytes(b"x" * 1024)
    (tier / "dataset.json").write_text(json.dumps({"periods": [{"name": "bench", "stats": {"stops": 10, "trips": 99}}]}))
    live = tmp_path / "france-live"
    for period in ("semaine", "samedi"):
        (live / period).mkdir(parents=True)
        (live / period / "routes.bin").write_bytes(b"x")
        (live / period / "school_routes.json").write_text(json.dumps({"lines": 7}))
    (live / "horizon.json").write_text(json.dumps({"start": "2026-11-19", "end": "2026-12-18"}))
    (live / "dataset.json").write_text(json.dumps({"periods": [{"name": "semaine", "stats": {"trips": 5}},
                                                               {"name": "samedi", "stats": {"trips": 3}}]}))
    (tmp_path / "france-live.new").mkdir()          # a build under way is not a network
    found = {n["key"]: n for n in scan_networks(tmp_path)}
    assert set(found) == {"metropole-lyon", "france-live"}
    assert found["metropole-lyon"]["trips"] == 99 and found["metropole-lyon"]["kind"] == "un jour"
    assert found["france-live"]["kind"] == "à jour" and found["france-live"]["school"] == 7
    assert found["france-live"]["periods"] == ["semaine", "samedi"] and "2026-12-18" in found["france-live"]["note"]


def test_tasks_build_their_command_lines():
    refresh = tasks.task("refresh")
    command = refresh.command("--force")
    assert command[1:] == ["-u", "-m", "gtfs_bench.refresh", "--force"]
    schedule = tasks.schedule_command("04:30")
    assert "Register-ScheduledTask" in schedule and "04:30" in schedule and "refresh.ps1" in schedule
    assert tasks.task("schedule").command(schedule)[0] == "powershell.exe"
    assert {t.group for t in tasks.TASKS} == {"Données à jour", "Chaîne du notebook", "Mesures", "Maintenance"}
    assert tasks.environment()["PYTHONIOENCODING"] == "utf-8"


def test_map_shows_names_scale_and_dashed_walks():
    outline = [[(42.0, -4.0), (51.0, -4.0), (51.0, 8.0), (42.0, 8.0), (42.0, -4.0)]]
    wide = mapview.draw(100, 30, None, outline, zoom=False).plain
    assert "Paris" in wide and "Lyon" in wide and "km" in wide            # cities and the scale bar
    trip = mapview.draw(100, 30, journey(), outline, zoom=True).plain
    assert "Bellecour" in trip and "Gare Part-Dieu" in trip               # start and end named
    lines = trip.split("\n")
    assert len(lines) == 30 and all(len(line) == 100 for line in lines)
    assert "km" in lines[-1]
    legend = mapview.legend(journey()).plain
    assert "D" in legend and "B" in legend and "à pied" in legend


def test_console_tabs_and_an_action_run():
    async def scenario():
        app = make_app(FakeServer())
        async with app.run_test(size=(160, 50)) as pilot:
            await wait_ready(app, pilot)
            for key, tab in (("f2", "tab-catalogue"), ("f3", "tab-networks"), ("f5", "tab-settings"),
                             ("f6", "tab-results"), ("f7", "tab-help"), ("f1", "tab-route")):
                await pilot.press(key)
                await pilot.pause(0.1)
                assert app.query_one("#tabs").active == tab
            catalogue = app.query_one("#catalogue")
            assert len(catalogue.rows) > 400 and catalogue.query_one("#cat-table").row_count > 0
            catalogue.query_one("#cat-search").value = "tcl"
            await pilot.pause(0.2)
            assert catalogue.query_one("#cat-table").row_count >= 1
            # An action runs in a subprocess and its output comes back into the log.
            actions = app.query_one("#actions")
            probe = tasks.Task("probe", "Sonde", "Maintenance", "Affiche la plateforme.", "platform", "", "instantané")
            app.action_tab("tab-actions")
            assert actions.start(probe, "")
            for _ in range(100):
                await pilot.pause(0.1)
                if actions.running is None:
                    break
            assert actions.running is None
            log_text = "\n".join(str(line.text) if hasattr(line, "text") else str(line)
                                 for line in actions.query_one("#act-log").lines)
            assert "Sonde : terminé" in log_text and ("Windows" in log_text or "Linux" in log_text)
    asyncio.run(scenario())
