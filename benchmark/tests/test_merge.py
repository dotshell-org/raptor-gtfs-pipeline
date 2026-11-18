"""Normalization and merge on three tiny synthetic feeds: urban, regional aggregate, national.

The feeds collide on ids, share a trip, carry homonyms, a station, a stop abroad, a
frequency-based trip, a missing time, a forbidden transfer, and a national train that
leaves the region: every rule of the merge has something to act on.
"""

import csv
import datetime as dt
import io
import zipfile

import pandas as pd
import pytest
import shapely

from gtfs_bench import merge as merge_module
from gtfs_bench.merge import MergeParams, Tier, merge_tier, tiers_from_catalog
from gtfs_bench.names import disambiguate, implicit_transfer_pairs, name_key
from gtfs_bench.normalize import Window, connect, is_current, normalize_feed
from gtfs_bench.transfers import TransferParams, walking_transfers

WEEK = Window.week_of(dt.date(2026, 12, 1))          # Mon 30 Nov – Sun 6 Dec 2026
MAINLAND = shapely.box(-5.0, 41.0, 6.0, 51.5)        # leaves Geneva (6.14 E) out
AURA = shapely.box(2.5, 44.0, 7.0, 46.5)             # Lyon and Villefranche, not Paris
WEEKDAYS = "1,1,1,1,1,0,0"

FEEDS = {
    "urb": {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,TCL test,https://x,Europe/Paris\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
                     "U1,Gare,45.7600,4.8600,0,STA\nU2,Mairie,45.7610,4.8610,,\nU3,Bellecour,45.7578,4.8320,,\n"
                     "STA,Gare,45.7600,4.8600,1,\nGEN,Genève,46.2044,6.1432,,\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,A,1,3\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WK,T1\nR1,WK,T2\nR1,WK,T3\nR1,WK,F1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "T1,08:00:00,08:00:00,U1,1\nT1,08:05:00,08:05:00,U2,2\nT1,08:10:00,08:10:00,U3,3\n"
                          "T2,09:00:00,09:00:00,U1,1\nT2,,,U2,2\nT2,09:20:00,09:20:00,U3,3\n"
                          "T3,10:00:00,10:00:00,U3,1\nT3,10:10:00,10:10:00,U1,2\nT3,11:00:00,11:00:00,GEN,3\n"
                          "F1,00:00:00,00:00:00,U1,1\nF1,00:10:00,00:10:00,U3,2\n",
        "frequencies.txt": "trip_id,start_time,end_time,headway_secs\nF1,07:00:00,08:00:00,1200\n",
        "calendar.txt": f"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWK,{WEEKDAYS},20261102,20261218\n",
        "calendar_dates.txt": "service_id,date,exception_type\nWK,20261202,2\n",
        "transfers.txt": "from_stop_id,to_stop_id,transfer_type,min_transfer_time\nU1,U2,2,120\nU2,U3,3,\n",
    },
    "agg": {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nX,Network X,https://x,Europe/Paris\nY,Network Y,https://y,Europe/Paris\n",
        # Same ids as "urb" on purpose: the prefixes must keep them apart.
        "stops.txt": "﻿stop_id, stop_name ,stop_lat,stop_lon\n"
                     "U1,Gare,45.7600,4.8600\nU2,Mairie,45.7610,4.8610\nU3,Bellecour,45.7578,4.8320\nS4,Mairie,45.9900,4.7200\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nRX,X,X1,3\nRY,Y,Y1,3\n",
        "trips.txt": "route_id,service_id,trip_id\nRX,WK2,T1\nRX,WK2,T9\nRY,WK2,TY\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "T1,08:00:00,08:00:00,U1,1\nT1,08:05:00,08:05:00,U2,2\nT1,08:10:00,08:10:00,U3,3\n"
                          "T9,07:00:00,07:00:00,S4,1\nT9,07:40:00,07:40:00,U1,2\n"
                          "TY,07:00:00,07:00:00,U1,1\nTY,07:05:00,07:05:00,U2,2\n",
        "calendar.txt": f"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWK2,{WEEKDAYS},20261101,20261231\n",
        "calendar_dates.txt": "service_id,date,exception_type\nWK2,20261202,2\n",
    },
    "nat": {
        "agency.txt": "agency_name,agency_url,agency_timezone\nSNCF,https://sncf,Europe/Paris\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     "StopPoint:OCETrain TER-1,Lyon Part-Dieu,45.7606,4.8596\nStopPoint:OCETrain TER-2,Paris Gare de Lyon,48.8443,2.3730\n"
                     "StopPoint:OCETrain TER-3,Villefranche,45.9850,4.7190\nStopPoint:OCETGV INOUI-1,Lyon Part-Dieu,45.7606,4.8596\n"
                     "StopPoint:OCETGV INOUI-2,Paris Gare de Lyon,48.8443,2.3730\n",
        "routes.txt": "route_id,route_short_name,route_type\nTER,TER,2\nTGV,TGV,2\n",
        "trips.txt": "route_id,service_id,trip_id\nTER,D,TN1\nTER,D,TN2\nTER,D,TN3\nTGV,D,TGV1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "TN1,06:00:00,06:00:00,StopPoint:OCETrain TER-2,1\nTN1,08:00:00,08:00:00,StopPoint:OCETrain TER-1,2\n"
                          "TN2,09:00:00,09:00:00,StopPoint:OCETrain TER-1,1\nTN2,09:30:00,09:30:00,StopPoint:OCETrain TER-3,2\n"
                          "TN3,10:00:00,10:00:00,StopPoint:OCETrain TER-3,1\nTN3,10:30:00,10:30:00,StopPoint:OCETrain TER-1,2\n"
                          "TN3,12:30:00,12:30:00,StopPoint:OCETrain TER-2,3\n"
                          "TGV1,07:00:00,07:00:00,StopPoint:OCETGV INOUI-2,1\nTGV1,09:00:00,09:00:00,StopPoint:OCETGV INOUI-1,2\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nD,1,1,1,1,1,1,1,20261101,20261231\n",
    },
}

ROWS = {
    "urb": dict(feed_id="urb", include=True, layer="regional", region_code="84", region_name="AURA", metropole="lyon",
                priority="10", clip=False, keep_agencies="", drop_agencies="", keep_stop_ids="", drop_stop_ids=""),
    "agg": dict(feed_id="agg", include=True, layer="regional", region_code="84", region_name="AURA", metropole="",
                priority="30", clip=False, keep_agencies="", drop_agencies="^(Network Y)$", keep_stop_ids="", drop_stop_ids=""),
    "nat": dict(feed_id="nat", include=True, layer="regional", region_code="FR", region_name="National", metropole="",
                priority="15", clip=True, keep_agencies="", drop_agencies="",
                keep_stop_ids="^StopPoint:OCE(Train TER|Car TER|TramTrain|Navette)-", drop_stop_ids=""),
}


def fake_communes(lat, lon):
    return ["Villefranche-sur-Saône" if la > 45.9 else "Lyon 3e Arrondissement" if lo > 4.85 else "Lyon 2e Arrondissement"
            for la, lo in zip(lat, lon)]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("bench")
    extracted, normalized, merged = root / "extracted", root / "normalized", root / "merged"
    for feed_id, files in FEEDS.items():
        (extracted / feed_id).mkdir(parents=True)
        for name, text in files.items():
            (extracted / feed_id / name).write_text(text, encoding="utf-8")
    con = connect("1GB")
    reports = {f: normalize_feed(ROWS[f], WEEK, con, extracted, normalized, source_sha256="x", area=MAINLAND) for f in FEEDS}
    con.close()
    original_area = merge_module._area
    merge_module._area = lambda code: AURA if code == "84" else MAINLAND
    try:
        tier = Tier("region:84", "region", "AURA", tuple(ROWS.values()), area_code="84")
        region = merge_tier(tier, MergeParams(reference_date=dt.date(2026, 12, 1)), normalized, merged,
                            commune_lookup=fake_communes, progress=lambda s: None)
        metro = merge_tier(Tier("metropole:lyon", "metropole", "Lyon", (ROWS["urb"],)), MergeParams(), normalized, merged,
                           commune_lookup=fake_communes, progress=lambda s: None)
    finally:
        merge_module._area = original_area
    return dict(root=root, reports=reports, region=region, metro=metro,
                region_zip=merged / "region" / "region-84.zip", metro_zip=merged / "metropole" / "metropole-lyon.zip")


def read(zip_path, name):
    with zipfile.ZipFile(zip_path) as archive:
        return list(csv.DictReader(io.StringIO(archive.read(f"{name}.txt").decode("utf-8"))))


# ── normalize ────────────────────────────────────────────────────────────────────────


def test_normalize_report(built):
    urb = built["reports"]["urb"]
    assert urb.stops_not_physical == 1            # the station
    assert urb.stops_outside_france == 1          # Geneva
    assert urb.trips_expanded_from_frequencies == 3   # 07:00, 07:20, 07:40
    assert urb.stop_times_interpolated == 1
    assert urb.transfers_out == 1                 # the forbidden one is gone
    assert urb.service_dates_out == 4             # Mon–Fri but Wednesday 2 Dec
    agg = built["reports"]["agg"]
    assert agg.agency_filter_matches == 1 and agg.agencies_dropped == ["Network Y"]
    nat = built["reports"]["nat"]
    assert nat.trips_dropped_by_stop_filter == 1  # the TGV


def test_cached_normalization_is_reused(built):
    root = built["root"]
    assert is_current(root / "normalized" / "urb", ROWS["urb"], WEEK, "x")
    assert not is_current(root / "normalized" / "urb", ROWS["urb"], Window.week_of(dt.date(2026, 12, 8)), "x")
    assert not is_current(root / "normalized" / "urb", {**ROWS["urb"], "drop_agencies": "^(Other)$"}, WEEK, "x")


# ── merge ────────────────────────────────────────────────────────────────────────────


def test_ids_are_prefixed_and_do_not_collide(built):
    stops = {s["stop_id"] for s in read(built["region_zip"], "stops")}
    assert {"urb:U1", "agg:U1"} <= stops
    trip_ids = [t["trip_id"] for t in read(built["region_zip"], "trips")]
    assert len(trip_ids) == len(set(trip_ids))


def test_a_trip_carried_twice_is_kept_once_from_the_preferred_feed(built):
    trips = {t["trip_id"] for t in read(built["region_zip"], "trips")}
    assert "urb:T1" in trips and "agg:T1" not in trips
    assert built["region"].duplicate_trips_by_feed == {"agg -> urb": 1}


def test_agency_filter_removes_its_trips(built):
    trips = {t["trip_id"] for t in read(built["region_zip"], "trips")}
    assert "agg:TY" not in trips
    assert {a["agency_name"] for a in read(built["region_zip"], "agency")} == {"TCL test", "Network X", "SNCF"}


def test_frequency_trips_and_interpolated_time(built):
    times = read(built["region_zip"], "stop_times")
    expanded = sorted({t["trip_id"] for t in times if t["trip_id"].startswith("urb:F1@")})
    assert expanded == ["urb:F1@25200", "urb:F1@26400", "urb:F1@27600"]
    first = [t for t in times if t["trip_id"] == "urb:F1@26400"]
    assert [t["departure_time"] for t in sorted(first, key=lambda t: int(t["stop_sequence"]))] == ["07:20:00", "07:30:00"]
    u2 = next(t for t in times if t["trip_id"] == "urb:T2" and t["stop_id"] == "urb:U2")
    # Interpolated along distance: U2 is ~140 m from U1 and ~2.3 km from U3.
    assert "09:00:00" < u2["arrival_time"] < "09:05:00"


def test_national_train_is_clipped_to_the_region(built):
    trips = {t["trip_id"] for t in read(built["region_zip"], "trips")}
    assert "nat:TN1" not in trips                 # Paris → Lyon: one stop in the region
    assert "nat:TGV1" not in trips                # not a TER
    tn3 = [t["stop_id"] for t in read(built["region_zip"], "stop_times") if t["trip_id"] == "nat:TN3"]
    assert tn3 == ["nat:StopPoint:OCETrain TER-3", "nat:StopPoint:OCETrain TER-1"]
    assert built["region"].trips_clipped_away == 1


def test_distant_homonyms_are_renamed_close_ones_are_not(built):
    names = {s["stop_id"]: s["stop_name"] for s in read(built["region_zip"], "stops")}
    assert names["urb:U2"] == "Mairie (Lyon 3e)"
    assert names["agg:S4"] == "Mairie (Villefranche-sur-Saône)"
    assert names["urb:U1"] == names["agg:U1"] == "Gare"   # same place, two feeds: still linked
    # agg:U2 only served the duplicate trip and the filtered agency: nothing uses it any more.
    assert "agg:U2" not in names


def test_transfers_both_ways_and_producer_time_wins(built):
    transfers = {(t["from_stop_id"], t["to_stop_id"]): int(t["min_transfer_time"]) for t in read(built["region_zip"], "transfers")}
    assert transfers[("urb:U1", "urb:U2")] == 120          # from the feed
    assert transfers[("urb:U2", "urb:U1")] >= 60           # generated, reverse direction
    assert transfers[("urb:U1", "agg:U1")] == 60           # same spot, two feeds: the floor
    assert ("urb:U2", "urb:U3") not in transfers or transfers[("urb:U2", "urb:U3")] > 0
    assert all(t["transfer_type"] == "2" for t in read(built["region_zip"], "transfers"))


def test_written_feed_is_consistent(built):
    assert built["region"].integrity_problems == []
    assert {a["agency_timezone"] for a in read(built["region_zip"], "agency")} == {"Europe/Paris"}
    dates = read(built["region_zip"], "calendar_dates")
    assert {d["exception_type"] for d in dates} == {"1"}
    assert "20261202" not in {d["date"] for d in dates if d["service_id"] == "urb:WK"}
    with zipfile.ZipFile(built["region_zip"]) as archive:
        assert sorted(archive.namelist()) == sorted(
            ["agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar_dates.txt", "transfers.txt", "feed_info.txt"])


def test_reference_day_counts(built):
    # Tuesday 1 Dec: urb T1, T2, T3 and the three frequency runs; agg T9; nat TN2, TN3.
    region = built["region"]
    assert region.reference_date == "2026-12-01"
    assert region.trips_on_reference_date == 9
    assert region.stop_times_on_reference_date == 20
    assert built["metro"].trips_on_reference_date == 0   # no reference date asked


def test_trips_per_day_reads_raw_calendars(built):
    from gtfs_bench.normalize import trips_per_day

    days = trips_per_day(ROWS["urb"], WEEK, None, built["root"] / "extracted")
    by_day = {d.date(): n for d, n in zip(days["date"], days["trips"])} if hasattr(days["date"].iloc[0], "date") else dict(zip(days["date"], days["trips"]))
    assert by_day[dt.date(2026, 12, 1)] == 4            # T1, T2, T3, F1 template: raw, before expansion
    assert dt.date(2026, 12, 2) not in by_day           # removed by calendar_dates
    assert dt.date(2026, 12, 5) not in by_day           # Saturday


def test_metropole_tier_holds_only_its_network(built):
    assert {s["stop_id"].split(":")[0] for s in read(built["metro_zip"], "stops")} == {"urb"}
    assert built["metro"].feeds == ["urb"]


def test_pattern_overlaps_finds_the_network_carried_twice(built):
    from gtfs_bench.merge import pattern_overlaps

    overlaps = pattern_overlaps(["urb", "agg", "nat"], built["root"] / "normalized", min_shared=1)
    pairs = {(r.feed_a, r.feed_b): r.shared_patterns for r in overlaps.itertuples()}
    assert pairs == {("agg", "urb"): 1}   # T1's stop sequence; times play no part


def test_tiers_from_catalog():
    tiers = tiers_from_catalog(list(ROWS.values()))
    assert [r["feed_id"] for r in tiers["metropole:lyon"].rows] == ["urb"]
    assert sorted(r["feed_id"] for r in tiers["region:84"].rows) == ["agg", "nat", "urb"]
    assert tiers["france"].area_code == "mainland"


def test_csv_quirks_quoted_line_break_apostrophes_latin1(tmp_path):
    """M TAG's stops hold a quoted line break; names carry apostrophes; some feeds are Latin-1."""
    from tests.gtfs_fixtures import MINIMAL_FEED

    folder = tmp_path / "extracted" / "quirky"
    folder.mkdir(parents=True)
    files = dict(MINIMAL_FEED)
    files["stops.txt"] = ('stop_id,stop_name,stop_desc,stop_lat,stop_lon\n'
                          'S1,"L\'Isle-d\'Abeau","quai\nnord",45.75,4.85\n'
                          'S2,"Le ""Grand"" Café",,45.76,4.86\n')
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    row = dict(ROWS["urb"], feed_id="quirky", metropole="")
    report = normalize_feed(row, WEEK, None, tmp_path / "extracted", tmp_path / "normalized", area=MAINLAND)
    assert report.stops_out == 2
    con = connect("1GB")
    names = sorted(r[0] for r in con.execute(
        f"SELECT stop_name FROM read_parquet('{(tmp_path / 'normalized' / 'quirky' / 'stops.parquet').as_posix()}')").fetchall())
    assert names == ["L'Isle-d'Abeau", 'Le "Grand" Café']

    latin = tmp_path / "extracted" / "latin"
    latin.mkdir()
    for name, text in files.items():
        (latin / name).write_bytes(text.replace("Café", "Cafè").encode("latin-1"))
    report = normalize_feed(dict(row, feed_id="latin"), WEEK, con, tmp_path / "extracted", tmp_path / "normalized", area=MAINLAND)
    assert report.csv_mode.startswith("latin-1") and report.stops_out == 2
    con.close()


# ── names and transfers on their own ─────────────────────────────────────────────────


def test_name_key_and_implicit_pairs():
    assert name_key("GARE  S.N.C.F.") == name_key("Gare SNCF") == "gare sncf"
    assert name_key("Église St-Jean") == name_key("EGLISE ST JEAN") == "eglise st jean"
    assert implicit_transfer_pairs(pd.Series(["A", "A", "A", "B"])) == 6


def test_chained_homonyms_form_one_place():
    # Three "Quai" 400 m apart in a line: A–B and B–C are within 500 m, so one place.
    stops = pd.DataFrame({"stop_id": ["a", "b", "c", "d"], "stop_name": ["Quai"] * 4,
                          "lat": [45.0, 45.0036, 45.0072, 47.0], "lon": [4.0] * 4})
    names, report = disambiguate(stops, lambda lat, lon: ["Far" if la > 46 else "Near" for la in lat])
    assert list(names) == ["Quai (Near)"] * 3 + ["Quai (Far)"]
    assert report.implicit_pairs_before == 12 and report.implicit_pairs_after == 6


def test_walking_transfers():
    stops = pd.DataFrame({"stop_id": ["a", "b", "c"], "lat": [45.0, 45.0018, 45.01], "lon": [4.0, 4.0, 4.0]})
    out = walking_transfers(stops, TransferParams(radius_m=300, max_neighbors=5, walk_speed_mps=1.0, floor_s=60))
    pairs = {(r.from_stop_id, r.to_stop_id): r.min_transfer_time for r in out.itertuples()}
    assert set(pairs) == {("a", "b"), ("b", "a")}       # c is 1.1 km away
    assert 195 <= pairs[("a", "b")] <= 205             # 200 m at 1 m/s
