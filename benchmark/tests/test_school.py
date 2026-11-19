"""School lines: the rules that find them, keep_routes, and the route numbers the engine gets."""

import datetime as dt
import json
import zipfile

import pandas as pd
import shapely

from gtfs_bench import school
from gtfs_bench.normalize import Window, connect, normalize_feed

DAY = dt.date(2026, 11, 24)                  # a Tuesday
WEEK = Window.week_of(DAY)
MAINLAND = shapely.box(-5.0, 41.0, 6.0, 51.5)
CALENDAR = ("service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WK,1,1,1,1,1,0,0,20261101,20261231\n")

# Feed "mix": ordinary and school lines side by side. (route_id, short, long, type, trips a day)
MIX_ROUTES = [
    ("R1", "1", "Gare <> Centre", 3, 8),                   # ordinary
    ("R2", "12", "Lycée Ampère <> Gare", 3, 2),            # serves a lycée, twice a day: few runs
    ("R3", "JD5", "Collège X (Vaugneray)", 713, 2),        # route_type 713
    ("R4", "S5", "Ligne scolaire S5", 3, 2),               # the name says so
    ("R5", "Ts30", "Mordelles <> Le Rheu", 3, 2),          # the feed's own convention
    ("R6", "20", "Lycée International <> Arènes", 3, 9),   # ends at a lycée, runs all day: ordinary
]


def feed_files(routes, agency="Mix"):
    stops = "stop_id,stop_name,stop_lat,stop_lon\nA,Alpha,45.70,4.80\nB,Beta,45.71,4.81\n"
    route_rows = "route_id,route_short_name,route_long_name,route_type\n" + "".join(
        f"{r},{s},{l},{t}\n" for r, s, l, t, _ in routes)
    trips, times = "route_id,service_id,trip_id\n", "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    for route_id, *_, runs in routes:
        for k in range(runs):
            trip = f"{route_id}-{k}"
            trips += f"{route_id},WK,{trip}\n"
            times += f"{trip},{7 + k:02d}:00:00,{7 + k:02d}:00:00,A,1\n{trip},{7 + k:02d}:10:00,{7 + k:02d}:10:00,B,2\n"
    return {"agency.txt": f"agency_name,agency_url,agency_timezone\n{agency},https://x,Europe/Paris\n",
            "stops.txt": stops, "routes.txt": route_rows, "trips.txt": trips, "stop_times.txt": times,
            "calendar.txt": CALENDAR}


ROWS = [
    dict(feed_id="mix", school=r"^Ts\d", keep_routes=""),
    # A school copy that also carries the regular line A: keep_routes keeps only its S lines.
    dict(feed_id="sco", school="all", keep_routes="^S"),
]
FEEDS = {"mix": feed_files(MIX_ROUTES), "sco": feed_files([("S1", "S1", "Circuit 1", 3, 2), ("A", "A", "Regular A", 3, 5)])}


def normalized(tmp_path):
    extracted, out = tmp_path / "extracted", tmp_path / "normalized"
    for feed_id, files in FEEDS.items():
        (extracted / feed_id).mkdir(parents=True)
        for name, text in files.items():
            (extracted / feed_id / name).write_text(text, encoding="utf-8")
    con = connect("1GB")
    reports = {row["feed_id"]: normalize_feed({**row, "drop_agencies": "", "keep_agencies": ""}, WEEK, con, extracted, out,
                                              source_sha256="x", area=MAINLAND) for row in ROWS}
    con.close()
    return out, reports


def test_rules_in_order():
    def rule(short, long, route_type=3, trips=2, feed_school=""):
        return school.classify({"route_short_name": short, "route_long_name": long, "route_type": route_type},
                               feed_school, trips)
    assert rule("1", "Gare <> Centre", trips=40) is None
    assert rule("JD5", "Collège X", route_type=713) == "route_type"
    assert rule("S35", "Scolaire S35") == "name" and rule("SBON", "Services scolaires Bons") == "name"
    assert rule("SCO204", "LIGNE 204") == "name"
    assert rule("87", "Cité Scolaire Rive Gauche / Frouzins", trips=40) is None   # a stop name, busy line
    assert rule("87", "Cité Scolaire Rive Gauche / Frouzins", trips=3) == "few runs"
    assert rule("Ts30", "Mordelles <> Le Rheu", feed_school=r"^Ts\d") == "feed rule"
    assert rule("A", "Anything", trips=50, feed_school="all") == "feed"
    assert rule("L2", "Arènes / Colomiers Lycée International", trips=120) is None


def test_school_lines_of_normalized_feeds(tmp_path):
    out, reports = normalized(tmp_path)
    assert reports["sco"].routes_out == 1 and reports["sco"].trips_dropped_by_agency == 5   # keep_routes
    lines = school.school_routes(ROWS, DAY, out).set_index("route_id")
    assert pd.isna(lines.loc["mix:R1", "rule"]) and pd.isna(lines.loc["mix:R6", "rule"])
    assert lines.loc["mix:R2", "rule"] == "few runs" and lines.loc["mix:R3", "rule"] == "route_type"
    assert lines.loc["mix:R4", "rule"] == "name" and lines.loc["mix:R5", "rule"] == "feed rule"
    assert lines.loc["sco:S1", "rule"] == "feed" and "sco:A" not in lines.index
    assert lines.loc["mix:R1", "trips_on_day"] == 8 and lines.loc["mix:R2", "trips_on_day"] == 2
    table = school.summary(lines.reset_index()).set_index("feed_id")
    assert table.loc["mix", "school_lines"] == 4 and table.loc["mix", "lines"] == 6
    assert table.loc["mix", "school_trips"] == 8 and table.loc["sco", "feed"] == 1
    review = tmp_path / "school_routes.csv"
    school.write_review(lines.reset_index(), review)
    assert review.read_text(encoding="utf-8").count("\n") == 1 + 5


def test_engine_route_ids_follow_routes_txt(tmp_path):
    archive = tmp_path / "tier.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("routes.txt", "route_id,route_short_name,route_long_name\n"
                                 "mix:R1,1,Gare\nmix:R2,12,Lycée\nmix:R2~1,12,Lycée\nmix:R3,,Collège X\nsco:S1,S1,\n")
    ids, names = school.engine_route_ids(archive, {"mix:R2", "mix:R3", "sco:S1"})
    assert ids == [1, 2, 3, 4]                                      # the extra pattern R2~1 too
    assert names == [(1, "12"), (2, "12"), (3, "Collège X"), (4, "S1")]   # short name, else long
    lines = pd.DataFrame({"route_id": ["mix:R2", "mix:R1"], "rule": ["few runs", None], "trips_on_day": [2, 8]})
    path = school.write_engine_file(tmp_path, ids, lines, DAY)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["routeIds"] == ids and payload["lines"] == 1 and payload["by_rule"]["few runs"] == 1
