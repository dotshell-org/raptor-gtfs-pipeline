"""Feed horizon, window, day types, and the daily refresh's decision to rebuild or not."""

import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from gtfs_bench import horizon, refresh
from gtfs_bench.horizon import Plan, choose_days, choose_window, day_type, easter, feed_table, public_holidays

D = dt.date


def test_public_holidays_and_easter():
    assert easter(2026) == D(2026, 4, 5) and easter(2027) == D(2027, 3, 28)
    days = public_holidays(2027)
    assert len(days) == 11 and D(2027, 3, 29) in days and D(2027, 5, 6) in days and D(2027, 5, 17) in days
    assert D(2026, 12, 25) in public_holidays(2026)


def test_a_date_is_served_by_its_day_type():
    assert day_type(D(2026, 11, 24), False) == "semaine"
    assert day_type(D(2026, 11, 28), False) == "samedi" and day_type(D(2026, 11, 29), False) == "dimanche"
    assert day_type(D(2026, 12, 25), True) == "dimanche"          # Christmas runs as a Sunday
    assert day_type(D(2026, 12, 22), True) == "vacances"          # a weekday in the Christmas holidays
    assert day_type(D(2026, 12, 22), False) == "semaine"          # … unless there is no holiday network


def days_table(feeds: dict[str, tuple[D, D, int]]) -> pd.DataFrame:
    """feed -> (first day, last day, trips each day)."""
    rows = []
    for feed, (first, last, trips) in feeds.items():
        for day in pd.date_range(first, last):
            rows.append({"feed_id": feed, "date": day, "trips": trips})
    return pd.DataFrame(rows)


def test_window_ends_with_the_first_feed_that_matters():
    start = D(2026, 11, 19)
    days = days_table({
        "big": (start, D(2026, 12, 17), 1000),     # 1000 of 1006 trips a day: it sets the end
        "ski": (start, D(2026, 11, 27), 2),        # tiny, stops early: lost, listed
        "small": (start, D(2026, 12, 12), 4),      # small, stops earlier: lost too
        "long": (start, D(2027, 3, 1), 0),         # no trip at all: ignored
    })
    table = feed_table(days, start)
    end, binding, lost = choose_window(table, start)
    assert end == D(2026, 12, 17) and binding["feed_id"] == "big"
    assert [f["feed_id"] for f in lost] == ["ski", "small"]
    # Strict: no feed may stop early, so the tiny ski shuttle sets the end.
    end, binding, lost = choose_window(table, start, max_feed_share=0.0, max_lost_share=0.0)
    assert end == D(2026, 11, 27) and binding["feed_id"] == "ski" and lost == []
    # Several small feeds together pass the lost-share limit: the one that tips it sets the end.
    end, binding, _ = choose_window(table, start, max_feed_share=0.5, max_lost_share=0.005)
    assert binding["feed_id"] == "small" and end == D(2026, 12, 12)


def test_day_types_come_from_one_week_ahead():
    days = days_table({"a": (D(2026, 11, 19), D(2027, 1, 20), 5)})
    # Thursday 19 Nov: that week's Tuesday is past, so the next week's three days.
    chosen = choose_days(days, D(2026, 11, 19), D(2026, 12, 17))
    assert chosen == {"semaine": D(2026, 11, 24), "samedi": D(2026, 11, 28), "dimanche": D(2026, 11, 29)}
    # A window reaching the Christmas holidays gets a holiday Tuesday too.
    chosen = choose_days(days, D(2026, 12, 14), D(2027, 1, 10))
    assert chosen["semaine"] == D(2026, 12, 15) and chosen["vacances"] in (D(2026, 12, 22), D(2026, 12, 29))
    with pytest.raises(ValueError):
        choose_days(days, D(2026, 11, 25), D(2026, 11, 27))     # no Sunday in the window


def test_plan_reads_back_and_maps_dates():
    plan = Plan(computed_on="2026-11-19", start="2026-11-19", end="2026-12-17", binding_feed="big", binding_share=0.9,
                days={"semaine": "2026-11-24", "samedi": "2026-11-28", "dimanche": "2026-11-29"})
    assert plan.network_for(D(2026, 12, 3)) == "semaine" and plan.network_for(D(2026, 12, 5)) == "samedi"
    assert plan.network_for(D(2026, 12, 18)) is None and plan.network_for(D(2026, 11, 18)) is None
    window = plan.normalization_window()
    assert (window.start, window.end) == (D(2026, 11, 23), D(2026, 11, 29))   # whole week: the cache holds
    assert Plan(**json.loads(plan.to_json())) == plan


def test_outputs(tmp_path):
    start = D(2026, 11, 19)
    days = days_table({"big": (start, D(2026, 12, 17), 1000), "ski": (start, D(2026, 11, 27), 2)})
    table = feed_table(days, start)
    end, binding, lost = choose_window(table, start)
    plan = Plan(computed_on=str(start), start=str(start), end=str(end), binding_feed=binding["feed_id"],
                binding_share=binding["share"], days={"semaine": "2026-11-24"}, lost=lost, feeds=2)
    paths = horizon.write_results(plan, table, days, tmp_path)
    assert paths["chart"].stat().st_size > 10_000
    assert pd.read_csv(paths["feeds"])["feed_id"].tolist() == ["ski", "big"]
    per_day = horizon.daily_coverage(days, table)
    assert per_day["trips_share"].iloc[0] == pytest.approx(1.0) and per_day["feeds"].iloc[-1] == 1


# ── the daily refresh: rebuild only when needed ──────────────────────────────────────


@pytest.fixture
def quiet_refresh(tmp_path, monkeypatch):
    """refresh() with everything slow or networked replaced: downloads, PAN, horizon, build."""
    plan = Plan(computed_on="2026-11-19", start="2026-11-19", end="2026-12-17", binding_feed="idfm", binding_share=0.27,
                days={"semaine": "2026-11-24", "samedi": "2026-11-28", "dimanche": "2026-11-29"})
    state = {"downloads": [], "built": 0, "plan": plan, "signatures": {}}
    live = tmp_path / "france-live"
    monkeypatch.setattr(refresh, "LIVE_DIR", live)
    monkeypatch.setattr(refresh, "live_rows", lambda: [{"feed_id": "a"}, {"feed_id": "b"}])
    monkeypatch.setattr(refresh, "read_manifest", lambda: {})
    monkeypatch.setattr(refresh, "SIGNATURES", tmp_path / "signatures.json")
    monkeypatch.setattr(refresh, "content_signature", lambda path: state["signatures"].get(path.stem, ""))
    monkeypatch.setattr(refresh, "download_all", lambda rows, progress: state["downloads"])
    monkeypatch.setattr(refresh, "make_plan", lambda rows, today, *limits: (state["plan"], None, None))
    monkeypatch.setattr(refresh, "write_results", lambda *a: None)

    def build(result, rows, java=None, progress=print):
        state["built"] += 1
        live.mkdir(exist_ok=True)
        (live / "horizon.json").write_text(result.to_json(), encoding="utf-8")
        return {"feeds": len(rows)}
    monkeypatch.setattr(refresh, "build_live", build)
    return state


def test_refresh_rebuilds_only_when_something_changed(quiet_refresh):
    state = quiet_refresh
    run = lambda day=D(2026, 11, 19): refresh.refresh(day, check_pan=False, progress=lambda s: None)
    first = run()
    assert first["rebuilt"] and "no live network yet" in first["reasons"] and state["built"] == 1
    assert not run()["rebuilt"] and state["built"] == 1                       # nothing changed
    state["downloads"] = [SimpleNamespace(feed_id="b", ok=True)]
    state["signatures"]["b"] = "s1"
    assert run()["changed"] == ["b"] and state["built"] == 2                  # a feed seen for the first time
    resent = run()                                                            # the server sends it again:
    assert not resent["rebuilt"] and resent["changed"] == [] and state["built"] == 2   # same files inside
    state["signatures"]["b"] = "s2"
    changed = run(D(2026, 11, 20))
    assert changed["rebuilt"] and changed["changed"] == ["b"] and state["built"] == 3
    state["plan"] = Plan(**{**json.loads(state["plan"].to_json()),
                            "days": {"semaine": "2026-12-01", "samedi": "2026-12-05", "dimanche": "2026-12-06"}})
    moved = run(D(2026, 11, 25))
    assert moved["rebuilt"] and "day types moved" in moved["reasons"][0] and state["built"] == 4


def test_content_signature_ignores_zip_timestamps(tmp_path):
    import zipfile
    for name, stamp in (("a.zip", (2026, 1, 1, 0, 0, 0)), ("b.zip", (2026, 11, 19, 20, 0, 0))):
        with zipfile.ZipFile(tmp_path / name, "w") as z:
            z.writestr(zipfile.ZipInfo("stops.txt", stamp), "stop_id\nA\n")
    with zipfile.ZipFile(tmp_path / "c.zip", "w") as z:
        z.writestr("stops.txt", "stop_id\nB\n")
    a, b, c = (refresh.content_signature(tmp_path / n) for n in ("a.zip", "b.zip", "c.zip"))
    assert a == b != c and refresh.content_signature(tmp_path / "missing.zip") == ""


def test_successors_are_newer_resources_of_feeds_about_to_stop(monkeypatch):
    table = pd.DataFrame({"feed_id": ["ski", "idfm"], "first_week_trips": [10, 1000],
                          "last_day": pd.to_datetime(["2026-11-27", "2027-06-30"])})
    monkeypatch.setattr(refresh, "read_catalog", lambda: [{"feed_id": "ski", "pan_resource_id": "1"}])
    candidates = [
        {"pan_dataset_id": "D1", "pan_resource_id": "2", "status": "ok", "end_date": "2027-04-25",
         "resource_title": "hiver", "start_date": "2026-12-12", "url": "u"},
        {"pan_dataset_id": "D1", "pan_resource_id": "1", "status": "ok", "end_date": "2026-11-27"},   # already in
        {"pan_dataset_id": "D9", "pan_resource_id": "3", "status": "ok", "end_date": "2027-12-31"},   # another dataset
    ]
    rows = [{"feed_id": "ski", "pan_dataset_id": "D1"}, {"feed_id": "idfm", "pan_dataset_id": "D2"}]
    found = refresh.successors(rows, table, D(2026, 11, 19), candidates)
    assert [(s["feed_id"], s["pan_resource_id"], s["title"]) for s in found] == [("ski", "2", "hiver")]
