"""N normalized feeds → one GTFS per tier: métropole ⊂ région ⊂ France.

    tiers = tiers_from_catalog(read_catalog())
    report = merge_tier(tiers["region:84"], MergeParams(), normalized_dir=NORMALIZED_DIR)

A tier is a set of catalogue rows and, for the rows marked `clip`, an area:

- métropole M: the rows whose `metropole` is M;
- région R: the rows whose `region_code` is R, plus the national rows clipped to R;
- France: every included row, clipped to mainland France.

Clipping keeps the trips that serve at least two stops inside the area, cut down to
those stops: a TER from Lyon to Paris belongs to the Auvergne-Rhône-Alpes tier as far as
its last stop in the region.

On top of the union, the merge:

1. drops a trip that another feed already carries: same stops (coordinates to ~10 m),
   same times, same service dates; the row with the lower `priority` keeps it;
2. drops stops, routes and agencies nothing uses any more;
3. renames homonym stops by place (see names.py);
4. adds walking transfers between nearby stops (see transfers.py), on top of the feeds'
   own;
5. writes a GTFS zip the pipeline reads as is, after checking that every reference in it
   resolves.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from . import geo
from .catalog import BENCHMARK_DIR, METROPOLES
from .names import NamesReport, disambiguate
from .normalize import NORMALIZED_DIR, TABLES, _sql_str, connect, insert_rows as _insert
from .transfers import TransferParams, walking_transfers

MERGED_DIR = BENCHMARK_DIR / "data" / "merged"
COORD_DECIMALS = 4  # ~11 m north-south, ~8 m east-west in France


@dataclass(frozen=True)
class Tier:
    key: str                 # "metropole:lyon", "region:84", "france"
    kind: str                # metropole | region | france
    name: str
    rows: tuple              # catalogue rows (dicts)
    area_code: str = ""      # region code, "mainland", or "" for no clipping

    @property
    def file_stem(self) -> str:
        return self.key.replace(":", "-")


@dataclass(frozen=True)
class MergeParams:
    name_radius_m: float = 500.0
    transfers: TransferParams = TransferParams()
    #: Service dates kept in the output; None keeps the whole normalization window.
    dates: tuple[dt.date, ...] | None = None
    #: The day the pipeline will convert: the report also counts what runs on it.
    reference_date: dt.date | None = None
    memory_limit: str = "6GB"


@dataclass
class TierReport:
    tier: str
    feeds: list
    dates: list
    reference_date: str = ""
    trips_on_reference_date: int = 0
    stop_times_on_reference_date: int = 0
    stops_on_reference_date: int = 0
    agencies: int = 0
    routes: int = 0
    trips: int = 0
    stop_times: int = 0
    stops: int = 0
    service_dates: int = 0
    transfers_from_feeds: int = 0
    transfers_generated: int = 0
    transfers: int = 0
    trips_clipped_away: int = 0
    duplicate_trips: int = 0
    duplicate_trips_by_feed: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)
    trips_by_feed: dict = field(default_factory=dict)
    integrity_problems: list = field(default_factory=list)
    zip_bytes: int = 0
    seconds: float = 0.0
    phase_seconds: dict = field(default_factory=dict)


def tiers_from_catalog(catalog: list[dict], layers: tuple[str, ...] = ("regional",)) -> dict[str, Tier]:
    """Every tier of the benchmark, keyed like Tier.key, in size order."""
    rows = [r for r in catalog if r["include"] and r["layer"] in layers]
    tiers: dict[str, Tier] = {}
    for key, (name, _) in METROPOLES.items():
        members = tuple(r for r in rows if r["metropole"] == key)
        if members:
            tiers[f"metropole:{key}"] = Tier(f"metropole:{key}", "metropole", name, members)
    for code in geo.MAINLAND_REGIONS:
        members = tuple(r for r in rows if r["region_code"] in (code, "FR"))
        if any(r["region_code"] == code for r in members):
            name = next(r["region_name"] for r in members if r["region_code"] == code)
            tiers[f"region:{code}"] = Tier(f"region:{code}", "region", name, members, area_code=code)
    tiers["france"] = Tier("france", "france", "France métropolitaine", tuple(rows), area_code="mainland")
    return tiers


def _area(code: str):
    return geo.mainland() if code == "mainland" else geo.region_area(code)


def _parquet_list(dirs: list[Path], table: str) -> str:
    return "[" + ", ".join(_sql_str((d / f"{table}.parquet").as_posix()) for d in dirs) + "]"


def merge_tier(tier: Tier, params: MergeParams = MergeParams(), normalized_dir: Path = NORMALIZED_DIR,
               out_dir: Path = MERGED_DIR, commune_lookup=None, progress=print) -> TierReport:
    started = time.time()
    commune_lookup = commune_lookup or geo.commune_names
    dirs = [normalized_dir / r["feed_id"] for r in tier.rows]
    missing = [d.name for d in dirs if not all((d / f"{t}.parquet").exists() for t in TABLES)]
    if missing:
        raise FileNotFoundError(f"{tier.key}: not normalized yet: {', '.join(missing)}")
    report = TierReport(tier=tier.key, feeds=[r["feed_id"] for r in tier.rows],
                        dates=[d.isoformat() for d in params.dates] if params.dates else [])
    con = connect(params.memory_limit)
    clock = [time.time()]

    def lap(phase: str) -> None:
        now = time.time()
        report.phase_seconds[phase] = round(now - clock[0], 1)
        clock[0] = now

    try:
        _load(con, tier, dirs, params)
        lap("load")
        report.trips_clipped_away = _clip(con, tier)
        lap("clip")
        report.duplicate_trips, report.duplicate_trips_by_feed = _deduplicate(con)
        _drop_orphans(con)
        lap("deduplicate")
        names_report = _rename(con, params, commune_lookup)
        report.names = asdict(names_report)
        lap("names")
        report.transfers_from_feeds, report.transfers_generated = _transfers(con, params)
        lap("transfers")
        out_dir = out_dir / tier.kind
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{tier.file_stem}.zip"
        with tempfile.TemporaryDirectory(dir=out_dir) as work:
            work_dir = Path(work)
            _export(con, work_dir, tier)
            lap("export")
            report.integrity_problems = check_integrity(con, work_dir)
            lap("integrity")
            _zip(work_dir, target)
            lap("zip")
        for table, attr in (("m_agency", "agencies"), ("m_routes", "routes"), ("m_trips", "trips"),
                            ("m_stop_times", "stop_times"), ("m_stops", "stops"),
                            ("m_dates", "service_dates"), ("m_transfers", "transfers")):
            setattr(report, attr, con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0])
        report.trips_by_feed = dict(con.execute(
            "SELECT feed_id, count(*) FROM m_trips GROUP BY feed_id ORDER BY 2 DESC").fetchall())
        if params.reference_date:
            report.reference_date = params.reference_date.isoformat()
            con.execute(f"""CREATE OR REPLACE TEMP TABLE day_trips AS SELECT trip_id FROM m_trips
                WHERE service_id IN (SELECT service_id FROM m_dates WHERE date = DATE {_sql_str(report.reference_date)})""")
            report.trips_on_reference_date = con.execute("SELECT count(*) FROM day_trips").fetchall()[0][0]
            report.stop_times_on_reference_date, report.stops_on_reference_date = con.execute(
                "SELECT count(*), count(DISTINCT stop_id) FROM m_stop_times WHERE trip_id IN (SELECT trip_id FROM day_trips)").fetchall()[0]
        report.zip_bytes = target.stat().st_size
        report.seconds = round(time.time() - started, 1)
        (out_dir / f"{tier.file_stem}.report.json").write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=1), encoding="utf-8")
        progress(f"{tier.key}: {report.trips} trips, {report.stops} stops, {report.stop_times} stop_times, "
                 f"{report.transfers} transfers, {report.duplicate_trips} duplicates dropped, "
                 f"{report.seconds} s" + (f", {len(report.integrity_problems)} INTEGRITY PROBLEMS" if report.integrity_problems else ""))
        return report
    finally:
        con.close()


def _load(con, tier: Tier, dirs: list[Path], params: MergeParams) -> None:
    for table in TABLES:
        name = "m_dates" if table == "calendar_dates" else f"m_{table}"
        con.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT * FROM read_parquet({_parquet_list(dirs, table)}, union_by_name = true)")
    priorities = [(r["feed_id"], int(r.get("priority") or 50), bool(r["clip"])) for r in tier.rows]
    con.execute("CREATE OR REPLACE TEMP TABLE m_feeds (feed_id VARCHAR, priority INTEGER, clip BOOLEAN)")
    _insert(con, "m_feeds", priorities)
    if params.dates:
        con.execute("CREATE OR REPLACE TEMP TABLE keep_dates (date DATE)")
        _insert(con, "keep_dates", [(d,) for d in params.dates])
        con.execute("DELETE FROM m_dates WHERE date NOT IN (SELECT date FROM keep_dates)")
        con.execute("DELETE FROM m_trips WHERE service_id NOT IN (SELECT service_id FROM m_dates)")
        con.execute("DELETE FROM m_stop_times WHERE trip_id NOT IN (SELECT trip_id FROM m_trips)")


def _clip(con, tier: Tier) -> int:
    """Cut the `clip` feeds down to the tier's area. Returns the trips that leave entirely."""
    clipped = [r["feed_id"] for r in tier.rows if r["clip"]]
    if not clipped or not tier.area_code:
        return 0
    stops = con.execute(f"""SELECT stop_id, lat, lon FROM m_stops
        WHERE feed_id IN (SELECT feed_id FROM m_feeds WHERE clip)""").fetchnumpy()
    inside = geo.inside(_area(tier.area_code), stops["lat"], stops["lon"])
    con.execute("CREATE OR REPLACE TEMP TABLE outside_area (stop_id VARCHAR)")
    _insert(con, "outside_area", [(s,) for s, ok in zip(stops["stop_id"], inside) if not ok])
    before = con.execute("SELECT count(*) FROM m_trips").fetchall()[0][0]
    con.execute("DELETE FROM m_stop_times WHERE stop_id IN (SELECT stop_id FROM outside_area)")
    con.execute("""DELETE FROM m_trips WHERE feed_id IN (SELECT feed_id FROM m_feeds WHERE clip)
        AND trip_id NOT IN (SELECT trip_id FROM m_stop_times GROUP BY trip_id HAVING count(*) >= 2)""")
    con.execute("DELETE FROM m_stop_times WHERE trip_id NOT IN (SELECT trip_id FROM m_trips)")
    return before - con.execute("SELECT count(*) FROM m_trips").fetchall()[0][0]


def _deduplicate(con) -> tuple[int, dict]:
    """Drop trips carried twice. Returns the count and, per (dropped feed → kept feed), how many."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE trip_sig AS
        SELECT st.trip_id,
               md5(string_agg(printf('%.{COORD_DECIMALS}f,%.{COORD_DECIMALS}f@%d', s.lat, s.lon, st.arrival_time), '|'
                              ORDER BY st.stop_sequence)) AS geo_sig
        FROM m_stop_times st JOIN m_stops s USING (stop_id) GROUP BY st.trip_id""")
    con.execute("""CREATE OR REPLACE TEMP TABLE service_sig AS
        SELECT service_id, md5(string_agg(CAST(date AS VARCHAR), ',' ORDER BY date)) AS dates_sig
        FROM m_dates GROUP BY service_id""")
    con.execute("""CREATE OR REPLACE TEMP TABLE ranked AS
        SELECT t.trip_id, t.feed_id, g.geo_sig, d.dates_sig,
               row_number() OVER (PARTITION BY g.geo_sig, d.dates_sig ORDER BY f.priority, t.feed_id, t.trip_id) AS rank,
               first_value(t.feed_id) OVER (PARTITION BY g.geo_sig, d.dates_sig ORDER BY f.priority, t.feed_id, t.trip_id) AS kept_feed
        FROM m_trips t JOIN trip_sig g USING (trip_id) JOIN service_sig d USING (service_id) JOIN m_feeds f USING (feed_id)""")
    pairs = con.execute("""SELECT feed_id || ' -> ' || kept_feed, count(*) FROM ranked WHERE rank > 1
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()
    con.execute("DELETE FROM m_trips WHERE trip_id IN (SELECT trip_id FROM ranked WHERE rank > 1)")
    con.execute("DELETE FROM m_stop_times WHERE trip_id NOT IN (SELECT trip_id FROM m_trips)")
    return sum(n for _, n in pairs), dict(pairs)


def _drop_orphans(con) -> None:
    con.execute("DELETE FROM m_stops WHERE stop_id NOT IN (SELECT DISTINCT stop_id FROM m_stop_times)")
    con.execute("DELETE FROM m_routes WHERE route_id NOT IN (SELECT DISTINCT route_id FROM m_trips)")
    con.execute("DELETE FROM m_agency WHERE agency_id NOT IN (SELECT DISTINCT agency_id FROM m_routes)")
    con.execute("DELETE FROM m_dates WHERE service_id NOT IN (SELECT DISTINCT service_id FROM m_trips)")
    con.execute("""DELETE FROM m_transfers WHERE from_stop_id NOT IN (SELECT stop_id FROM m_stops)
        OR to_stop_id NOT IN (SELECT stop_id FROM m_stops)""")


def _rename(con, params: MergeParams, commune_lookup) -> NamesReport:
    stops = con.execute("SELECT stop_id, stop_name, lat, lon FROM m_stops ORDER BY stop_id").df()
    new_names, report = disambiguate(stops, commune_lookup, params.name_radius_m)
    renamed = pd.DataFrame({"stop_id": stops["stop_id"], "new_name": new_names})
    renamed = renamed[new_names != stops["stop_name"].fillna("")]
    con.register("renamed_df", renamed)
    con.execute("UPDATE m_stops SET stop_name = r.new_name FROM renamed_df r WHERE m_stops.stop_id = r.stop_id")
    con.unregister("renamed_df")
    return report


def _transfers(con, params: MergeParams) -> tuple[int, int]:
    """Feed transfers, then generated walking ones for the pairs the feeds say nothing about.

    A producer's time wins over the generated one: it may know of a long platform walk
    that the distance between two stop coordinates does not show.
    """
    from_feeds = con.execute("SELECT count(*) FROM m_transfers").fetchall()[0][0]
    stops = con.execute("SELECT stop_id, lat, lon FROM m_stops").df()
    generated = walking_transfers(stops, params.transfers)
    con.register("generated_df", generated)
    # A feed's transfer without a time is a plain "you may change here": give it the walk
    # time if the stops are near each other, else 0 as the pipeline would.
    con.execute("""CREATE OR REPLACE TEMP TABLE all_transfers AS
        SELECT f.from_stop_id, f.to_stop_id,
               coalesce(f.min_transfer_time, g.min_transfer_time, 0) AS min_transfer_time
        FROM m_transfers f LEFT JOIN generated_df g USING (from_stop_id, to_stop_id)
        UNION ALL
        SELECT g.from_stop_id, g.to_stop_id, g.min_transfer_time FROM generated_df g
        ANTI JOIN m_transfers f USING (from_stop_id, to_stop_id)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE m_transfers AS
        SELECT from_stop_id, to_stop_id, 2 AS transfer_type, min(min_transfer_time) AS min_transfer_time
        FROM all_transfers GROUP BY from_stop_id, to_stop_id""")
    con.unregister("generated_df")
    return from_feeds, len(generated)


def _export(con, work_dir: Path, tier: Tier) -> None:
    hms = "printf('%02d:%02d:%02d', {c} // 3600, ({c} % 3600) // 60, {c} % 60)"
    first, last = con.execute("SELECT min(date), max(date) FROM m_dates").fetchall()[0]
    files = {
        "agency": "SELECT agency_id, agency_name, agency_url, 'Europe/Paris' AS agency_timezone, agency_lang FROM m_agency ORDER BY agency_id",
        "stops": "SELECT stop_id, stop_name, round(lat, 6) AS stop_lat, round(lon, 6) AS stop_lon, zone_id FROM m_stops ORDER BY stop_id",
        "routes": """SELECT route_id, agency_id, route_short_name, route_long_name, route_type, route_color, route_text_color
                     FROM m_routes ORDER BY route_id""",
        "trips": "SELECT route_id, service_id, trip_id, direction_id FROM m_trips ORDER BY route_id, trip_id",
        "stop_times": f"""SELECT trip_id, {hms.format(c='arrival_time')} AS arrival_time, {hms.format(c='departure_time')} AS departure_time,
                          stop_id, stop_sequence FROM m_stop_times ORDER BY trip_id, stop_sequence""",
        "calendar_dates": "SELECT service_id, strftime(date, '%Y%m%d') AS date, 1 AS exception_type FROM m_dates ORDER BY service_id, date",
        "transfers": "SELECT from_stop_id, to_stop_id, transfer_type, min_transfer_time FROM m_transfers ORDER BY from_stop_id, to_stop_id",
        "feed_info": f"""SELECT 'raptor-gtfs-pipeline benchmark' AS feed_publisher_name,
                         'https://github.com/dotshell-org/raptor-gtfs-pipeline' AS feed_publisher_url, 'fr' AS feed_lang,
                         {_sql_str(first.strftime('%Y%m%d') if first else '')} AS feed_start_date,
                         {_sql_str(last.strftime('%Y%m%d') if last else '')} AS feed_end_date,
                         {_sql_str(tier.key + ' ' + dt.date.today().isoformat())} AS feed_version""",
    }
    for name, query in files.items():
        target = (work_dir / f"{name}.txt").as_posix()
        con.execute(f"COPY ({query}) TO {_sql_str(target)} (FORMAT csv, HEADER true, DELIMITER ',', QUOTE '\"')")


def check_integrity(con, folder: Path) -> list[str]:
    """Every reference of the written feed resolves; returns the problems found (none expected)."""
    def view(name):
        # Quote and escape stated, as when normalizing: the sniffer may otherwise take "'"
        # for the escape character and cut ids containing one in the wrong place.
        return (f"read_csv({_sql_str((folder / f'{name}.txt').as_posix())}, header = true, all_varchar = true, "
                f"quote = '\"', escape = '\"', parallel = false)")
    checks = {
        "stop_times.trip_id not in trips": f"SELECT count(*) FROM {view('stop_times')} WHERE trip_id NOT IN (SELECT trip_id FROM {view('trips')})",
        "stop_times.stop_id not in stops": f"SELECT count(*) FROM {view('stop_times')} WHERE stop_id NOT IN (SELECT stop_id FROM {view('stops')})",
        "trips.route_id not in routes": f"SELECT count(*) FROM {view('trips')} WHERE route_id NOT IN (SELECT route_id FROM {view('routes')})",
        "trips.service_id not in calendar_dates": f"SELECT count(*) FROM {view('trips')} WHERE service_id NOT IN (SELECT service_id FROM {view('calendar_dates')})",
        "routes.agency_id not in agency": f"SELECT count(*) FROM {view('routes')} WHERE agency_id NOT IN (SELECT agency_id FROM {view('agency')})",
        "transfers on unknown stops": f"""SELECT count(*) FROM {view('transfers')} WHERE from_stop_id NOT IN (SELECT stop_id FROM {view('stops')})
                                          OR to_stop_id NOT IN (SELECT stop_id FROM {view('stops')})""",
        "duplicate stop_id": f"SELECT count(*) - count(DISTINCT stop_id) FROM {view('stops')}",
        "duplicate trip_id": f"SELECT count(*) - count(DISTINCT trip_id) FROM {view('trips')}",
        "trips with fewer than 2 stops": f"""SELECT count(*) FROM (SELECT trip_id FROM {view('stop_times')} GROUP BY trip_id HAVING count(*) < 2)""",
        "stops without coordinates": f"SELECT count(*) FROM {view('stops')} WHERE TRY_CAST(stop_lat AS DOUBLE) IS NULL OR TRY_CAST(stop_lon AS DOUBLE) IS NULL",
    }
    problems = []
    for label, query in checks.items():
        count = con.execute(query).fetchall()[0][0]
        if count:
            problems.append(f"{label}: {count}")
    return problems


def pattern_overlaps(feed_ids: list[str], normalized_dir: Path = NORMALIZED_DIR, min_shared: int = 3,
                     memory_limit: str = "6GB") -> pd.DataFrame:
    """Feed pairs that run the same stop patterns: the catalogue may hold a network twice.

    A pattern is a trip's sequence of stop positions (to ~100 m), times ignored, so two
    versions of one timetable still match where trip deduplication, which compares times,
    would not. Sorted by the share of the smaller feed's patterns found in the other.
    """
    dirs = [normalized_dir / f for f in feed_ids]
    con = connect(memory_limit)
    try:
        con.execute(f"""CREATE TEMP TABLE fp AS SELECT DISTINCT t.feed_id,
                md5(string_agg(printf('%.3f,%.3f', s.lat, s.lon), '|' ORDER BY st.stop_sequence)) AS pattern
            FROM read_parquet({_parquet_list(dirs, 'stop_times')}) st
            JOIN read_parquet({_parquet_list(dirs, 'stops')}) s USING (stop_id)
            JOIN read_parquet({_parquet_list(dirs, 'trips')}, union_by_name = true) t USING (trip_id)
            GROUP BY st.trip_id, t.feed_id""")
        return con.execute(f"""
            WITH totals AS (SELECT feed_id, count(*) AS patterns FROM fp GROUP BY feed_id)
            SELECT a.feed_id AS feed_a, b.feed_id AS feed_b, count(*) AS shared_patterns,
                   ta.patterns AS patterns_a, tb.patterns AS patterns_b,
                   round(count(*) / least(ta.patterns, tb.patterns), 3) AS share_of_smaller
            FROM fp a JOIN fp b ON a.pattern = b.pattern AND a.feed_id < b.feed_id
            JOIN totals ta ON ta.feed_id = a.feed_id JOIN totals tb ON tb.feed_id = b.feed_id
            GROUP BY a.feed_id, b.feed_id, ta.patterns, tb.patterns
            HAVING count(*) >= {int(min_shared)}
            ORDER BY share_of_smaller DESC""").df()
    finally:
        con.close()


def _zip(folder: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".part")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.glob("*.txt")):
            archive.write(path, path.name)
    temporary.replace(target)
