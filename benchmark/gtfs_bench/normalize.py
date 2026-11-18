"""One feed → clean tables, ready to be merged (data/normalized/<feed_id>/<table>.parquet).

Everything the pipeline would trip over, or that two feeds would collide on, is settled
here, once per feed:

- every id gets the `feed_id:` prefix, references included, so feeds cannot collide;
- only physical stops with coordinates inside mainland France are kept (the pipeline
  reads neither location_type nor parent_station);
- the catalogue's agency and stop_id filters are applied;
- calendars become explicit service dates inside the merge window (calendar_dates only);
- frequencies.txt is expanded into trips (the pipeline does not read it);
- missing stop times are interpolated along the trip's distance (the pipeline drops a
  stop_time without one); trips whose first or last stop has no time are dropped;
- transfers keep only stop-to-stop rows that are not forbidden (the pipeline reads
  every row as a usable transfer and ignores transfer_type).

Times are stored as seconds since midnight of the service day. Shapes, fares, pathways
and the like are not carried: the pipeline does not need them to build routing data.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import geo
from .catalog import BENCHMARK_DIR

DATA_DIR = BENCHMARK_DIR / "data"
EXTRACTED_DIR = DATA_DIR / "extracted"
NORMALIZED_DIR = DATA_DIR / "normalized"
TMP_DIR = DATA_DIR / "tmp"

TABLES = ("agency", "stops", "routes", "trips", "stop_times", "calendar_dates", "transfers")
#: Bump when the normalized output changes, so cached feeds are rebuilt.
NORMALIZER_VERSION = 2


@dataclass(frozen=True)
class Window:
    """Inclusive range of service dates kept by the merge."""

    start: dt.date
    end: dt.date

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError("window ends before it starts")

    @classmethod
    def week_of(cls, day: dt.date) -> Window:
        monday = day - dt.timedelta(days=day.weekday())
        return cls(monday, monday + dt.timedelta(days=6))

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


class FeedError(RuntimeError):
    pass


def connect(memory_limit: str = "6GB", threads: int | None = None) -> duckdb.DuckDBPyConnection:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{memory_limit}'")
    con.execute(f"SET temp_directory = '{TMP_DIR.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")
    if threads:
        con.execute(f"SET threads = {int(threads)}")
    return con


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def insert_rows(con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple]) -> None:
    """Append rows to an existing table in one go. Nothing to do for an empty list (which
    executemany refuses), and no row-by-row round trips for a long one."""
    if not rows:
        return
    frame = pd.DataFrame(rows)
    con.register("_insert_rows", frame)
    try:
        con.execute(f"INSERT INTO {table} SELECT * FROM _insert_rows")
    finally:
        con.unregister("_insert_rows")


# ── Reading the feed's CSV files ─────────────────────────────────────────────────────


#: How the CSV files are read, tried in order until a feed goes through. The parallel
#: reader is the fast one, but it refuses a quoted field holding a line break (M TAG's
#: stops, Destineo's stop_times); a few producers still write Latin-1.
CSV_MODES = (("utf-8", True), ("utf-8", False), ("latin-1", False))


def _register_csv(con: duckdb.DuckDBPyConnection, folder: Path, name: str, required: bool = False,
                  encoding: str = "utf-8", parallel: bool = True) -> set[str]:
    """Expose <name>.txt as view raw_<name>: every column VARCHAR, names trimmed and lower-case.

    Returns the set of column names, empty if the file is absent or has no header.
    """
    path = folder / f"{name}.txt"
    if not path.exists() or path.stat().st_size == 0:
        if required:
            raise FeedError(f"{name}.txt is missing")
        con.execute(f"CREATE OR REPLACE TEMP VIEW raw_{name} AS SELECT NULL::VARCHAR AS _absent WHERE false")
        return set()
    # Quote and escape are GTFS's (RFC 4180): left to the sniffer, it sometimes picks "'"
    # as the escape character, which would garble names like L'Isle-d'Abeau.
    source = (f"read_csv({_sql_str(path.as_posix())}, header = true, all_varchar = true, "
              f"quote = '\"', escape = '\"', null_padding = true, strict_mode = false, "
              f"encoding = '{encoding}', parallel = {str(parallel).lower()})")
    try:
        columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    except duckdb.Error as error:
        raise FeedError(f"{name}.txt cannot be read: {error}") from error
    clean = {}
    for column in columns:
        key = column.replace("﻿", "").strip().lower()
        if key and key not in clean.values():
            clean[column] = key
    select = ", ".join(f'nullif(trim("{c.replace(chr(34), chr(34) * 2)}"), \'\') AS "{k}"' for c, k in clean.items())
    con.execute(f"CREATE OR REPLACE TEMP VIEW raw_{name} AS SELECT {select} FROM {source}")
    return set(clean.values())


def _col(columns: set[str], name: str, default: str = "NULL") -> str:
    return f'"{name}"' if name in columns else f"{default}::VARCHAR"


TIME_SQL = """CASE WHEN regexp_full_match({c}, '\\d{{1,3}}:\\d{{1,2}}:\\d{{1,2}}')
    THEN CAST(split_part({c}, ':', 1) AS INTEGER) * 3600
       + CAST(split_part({c}, ':', 2) AS INTEGER) * 60
       + CAST(split_part({c}, ':', 3) AS INTEGER) END"""


def _time(column: str) -> str:
    return TIME_SQL.format(c=column)


# ── The normalization itself ─────────────────────────────────────────────────────────


@dataclass
class FeedReport:
    feed_id: str
    version: int
    window: dict
    source_sha256: str
    filters: str
    agencies_in: int = 0
    agencies_dropped: list | None = None
    agency_filter_matches: int | None = None
    stops_in: int = 0
    stops_not_physical: int = 0
    stops_without_coordinates: int = 0
    stops_outside_france: int = 0
    stops_out: int = 0
    routes_out: int = 0
    trips_in: int = 0
    trips_dropped_by_agency: int = 0
    trips_dropped_by_stop_filter: int = 0
    trips_without_service_in_window: int = 0
    trips_expanded_from_frequencies: int = 0
    trips_without_end_times: int = 0
    trips_too_short: int = 0
    trips_out: int = 0
    stop_times_out: int = 0
    stop_times_interpolated: int = 0
    stop_times_on_dropped_stops: int = 0
    service_dates_out: int = 0
    transfers_in: int = 0
    transfers_out: int = 0
    csv_mode: str = ""
    seconds: float = 0.0


def filters_signature(row: dict) -> str:
    keys = ("keep_agencies", "drop_agencies", "keep_stop_ids", "drop_stop_ids")
    return hashlib.sha256(json.dumps({k: row.get(k, "") for k in keys}, sort_keys=True).encode()).hexdigest()[:16]


def is_current(out_dir: Path, row: dict, window: Window, source_sha256: str) -> bool:
    report_path = out_dir / "report.json"
    if not report_path.exists() or not all((out_dir / f"{t}.parquet").exists() for t in TABLES):
        return False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return (report.get("version") == NORMALIZER_VERSION and report.get("window") == window.as_dict()
            and report.get("source_sha256") == source_sha256 and report.get("filters") == filters_signature(row))


def _count(con, sql: str) -> int:
    return con.execute(f"SELECT count(*) FROM ({sql})").fetchall()[0][0]


def normalize_feed(row: dict, window: Window, con: duckdb.DuckDBPyConnection | None = None,
                   extracted_dir: Path = EXTRACTED_DIR, normalized_dir: Path = NORMALIZED_DIR,
                   source_sha256: str = "", force: bool = False, area=None) -> FeedReport:
    """Normalize one catalogue row's extracted feed. `area` defaults to mainland France."""
    started = dt.datetime.now()
    feed_id = row["feed_id"]
    folder = extracted_dir / feed_id
    out_dir = normalized_dir / feed_id
    if not force and is_current(out_dir, row, window, source_sha256):
        return FeedReport(**json.loads((out_dir / "report.json").read_text(encoding="utf-8")))
    if not (folder / "stops.txt").exists():
        raise FeedError(f"{folder} holds no feed: download it first")
    own = con is None
    con = con or connect()
    prefix = _sql_str(feed_id + ":")

    def attempt(encoding: str, parallel: bool) -> FeedReport:
        report = FeedReport(feed_id=feed_id, version=NORMALIZER_VERSION, window=window.as_dict(),
                            source_sha256=source_sha256, filters=filters_signature(row),
                            csv_mode=encoding + ("" if parallel else ", sequential"))
        cols = {name: _register_csv(con, folder, name, required=name in ("stops", "routes", "trips", "stop_times"),
                                    encoding=encoding, parallel=parallel)
                for name in ("agency", "stops", "routes", "trips", "stop_times", "calendar",
                             "calendar_dates", "frequencies", "transfers")}

        # Agencies. agency_id is optional in a single-agency feed: give it one.
        a = cols["agency"]
        if a:
            con.execute(f"""CREATE OR REPLACE TEMP TABLE n_agency AS
                SELECT coalesce({_col(a, 'agency_id')}, 'default') AS agency_id,
                       coalesce({_col(a, 'agency_name')}, {_sql_str(feed_id)}) AS agency_name,
                       coalesce({_col(a, 'agency_url')}, 'https://transport.data.gouv.fr') AS agency_url,
                       {_col(a, 'agency_lang')} AS agency_lang
                FROM raw_agency""")
        else:
            con.execute(f"""CREATE OR REPLACE TEMP TABLE n_agency AS SELECT 'default' AS agency_id,
                {_sql_str(feed_id)} AS agency_name, 'https://transport.data.gouv.fr' AS agency_url, NULL::VARCHAR AS agency_lang""")
        agencies = con.execute("SELECT agency_id, agency_name FROM n_agency").fetchall()
        report.agencies_in = len(agencies)
        kept_ids, dropped_names, matches = _filter_agencies(agencies, row.get("keep_agencies", ""), row.get("drop_agencies", ""))
        report.agencies_dropped, report.agency_filter_matches = dropped_names, matches
        con.execute("CREATE OR REPLACE TEMP TABLE kept_agency (agency_id VARCHAR)")
        insert_rows(con, "kept_agency", [(i,) for i in kept_ids])
        con.execute("DELETE FROM n_agency WHERE agency_id NOT IN (SELECT agency_id FROM kept_agency)")

        # Routes: an empty agency_id points at the feed's only (or first) agency.
        r = cols["routes"]
        first_agency = _sql_str(agencies[0][0]) if agencies else "'default'"
        con.execute(f"""CREATE OR REPLACE TEMP TABLE n_routes AS
            SELECT route_id, coalesce({_col(r, 'agency_id')}, {first_agency}) AS agency_id,
                   {_col(r, 'route_short_name')} AS route_short_name, {_col(r, 'route_long_name')} AS route_long_name,
                   coalesce(TRY_CAST({_col(r, 'route_type')} AS INTEGER), 3) AS route_type,
                   {_col(r, 'route_color')} AS route_color, {_col(r, 'route_text_color')} AS route_text_color
            FROM raw_routes WHERE route_id IS NOT NULL""")
        con.execute("DELETE FROM n_routes WHERE agency_id NOT IN (SELECT agency_id FROM kept_agency)")

        # Stops: physical ones, with coordinates, inside mainland France.
        s = cols["stops"]
        report.stops_in = _count(con, "SELECT * FROM raw_stops")
        location = _col(s, "location_type")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE cand_stops AS
            SELECT stop_id, coalesce({_col(s, 'stop_name')}, stop_id) AS stop_name,
                   TRY_CAST({_col(s, 'stop_lat')} AS DOUBLE) AS lat, TRY_CAST({_col(s, 'stop_lon')} AS DOUBLE) AS lon,
                   {_col(s, 'zone_id')} AS zone_id
            FROM raw_stops WHERE stop_id IS NOT NULL AND coalesce({location}, '0') IN ('0', '')""")
        report.stops_not_physical = report.stops_in - _count(con, "SELECT * FROM cand_stops")
        report.stops_without_coordinates = con.execute(
            "SELECT count(*) FROM cand_stops WHERE lat IS NULL OR lon IS NULL OR (abs(lat) < 1e-6 AND abs(lon) < 1e-6)").fetchall()[0][0]
        con.execute("DELETE FROM cand_stops WHERE lat IS NULL OR lon IS NULL OR (abs(lat) < 1e-6 AND abs(lon) < 1e-6)")
        coords = con.execute("SELECT stop_id, lat, lon FROM cand_stops").fetchnumpy()
        mask = geo.inside(area if area is not None else geo.mainland(), coords["lat"], coords["lon"])
        outside = [sid for sid, ok in zip(coords["stop_id"], mask) if not ok]
        report.stops_outside_france = len(outside)
        if outside:
            con.execute("CREATE OR REPLACE TEMP TABLE outside_stops (stop_id VARCHAR)")
            insert_rows(con, "outside_stops", [(i,) for i in outside])
            con.execute("DELETE FROM cand_stops WHERE stop_id IN (SELECT stop_id FROM outside_stops)")

        # Trips of kept routes.
        t = cols["trips"]
        report.trips_in = _count(con, "SELECT * FROM raw_trips")
        con.execute(f"""CREATE OR REPLACE TEMP TABLE cand_trips AS
            SELECT trip_id, route_id, service_id, coalesce(TRY_CAST({_col(t, 'direction_id')} AS INTEGER), 0) AS direction_id
            FROM raw_trips WHERE trip_id IS NOT NULL AND service_id IS NOT NULL""")
        before = _count(con, "SELECT * FROM cand_trips")
        con.execute("DELETE FROM cand_trips WHERE route_id NOT IN (SELECT route_id FROM n_routes)")
        report.trips_dropped_by_agency = before - _count(con, "SELECT * FROM cand_trips")

        # Service dates inside the window.
        _service_dates(con, cols["calendar"], cols["calendar_dates"], window)
        before = _count(con, "SELECT * FROM cand_trips")
        con.execute("DELETE FROM cand_trips WHERE service_id NOT IN (SELECT service_id FROM n_dates)")
        report.trips_without_service_in_window = before - _count(con, "SELECT * FROM cand_trips")

        # Stop times of those trips, in seconds.
        st = cols["stop_times"]
        con.execute(f"""CREATE OR REPLACE TEMP TABLE cand_st AS
            SELECT trip_id, stop_id, TRY_CAST({_col(st, 'stop_sequence')} AS INTEGER) AS seq,
                   {_time(_col(st, 'arrival_time'))} AS arr, {_time(_col(st, 'departure_time'))} AS dep
            FROM raw_stop_times
            WHERE trip_id IN (SELECT trip_id FROM cand_trips) AND stop_id IS NOT NULL""")
        con.execute("DELETE FROM cand_st WHERE seq IS NULL")

        # Catalogue filters on stop_ids, applied to whole trips (before any stop is dropped).
        before = _count(con, "SELECT * FROM cand_trips")
        if row.get("keep_stop_ids"):
            con.execute(f"""DELETE FROM cand_trips WHERE trip_id IN (SELECT trip_id FROM cand_st
                WHERE NOT regexp_matches(stop_id, {_sql_str(row['keep_stop_ids'])}))""")
        if row.get("drop_stop_ids"):
            con.execute(f"""DELETE FROM cand_trips WHERE trip_id IN (SELECT trip_id FROM cand_st
                WHERE regexp_matches(stop_id, {_sql_str(row['drop_stop_ids'])}))""")
        report.trips_dropped_by_stop_filter = before - _count(con, "SELECT * FROM cand_trips")
        con.execute("DELETE FROM cand_st WHERE trip_id NOT IN (SELECT trip_id FROM cand_trips)")

        # Stop times on stops that were dropped (stations, outside France…) go too.
        before = _count(con, "SELECT * FROM cand_st")
        con.execute("DELETE FROM cand_st WHERE stop_id NOT IN (SELECT stop_id FROM cand_stops)")
        report.stop_times_on_dropped_stops = before - _count(con, "SELECT * FROM cand_st")

        report.trips_expanded_from_frequencies = _expand_frequencies(con, cols["frequencies"])
        report.stop_times_interpolated, report.trips_without_end_times = _interpolate(con)

        before = _count(con, "SELECT * FROM cand_trips")
        con.execute("""DELETE FROM cand_trips WHERE trip_id NOT IN
            (SELECT trip_id FROM cand_st GROUP BY trip_id HAVING count(*) >= 2)""")
        report.trips_too_short = before - _count(con, "SELECT * FROM cand_trips")
        con.execute("DELETE FROM cand_st WHERE trip_id NOT IN (SELECT trip_id FROM cand_trips)")

        # Transfers: stop to stop, not forbidden, both ends kept.
        tr = cols["transfers"]
        if tr and "from_stop_id" in tr and "to_stop_id" in tr:
            report.transfers_in = _count(con, "SELECT * FROM raw_transfers")
            trip_level = " OR ".join(f'"{c}" IS NOT NULL' for c in ("from_trip_id", "to_trip_id", "from_route_id", "to_route_id") if c in tr) or "false"
            con.execute(f"""CREATE OR REPLACE TEMP TABLE cand_transfers AS
                SELECT DISTINCT from_stop_id, to_stop_id,
                       coalesce(TRY_CAST({_col(tr, 'transfer_type')} AS INTEGER), 0) AS transfer_type,
                       TRY_CAST({_col(tr, 'min_transfer_time')} AS INTEGER) AS min_transfer_time
                FROM raw_transfers
                WHERE from_stop_id IN (SELECT stop_id FROM cand_stops) AND to_stop_id IN (SELECT stop_id FROM cand_stops)
                  AND coalesce(TRY_CAST({_col(tr, 'transfer_type')} AS INTEGER), 0) IN (0, 1, 2)
                  AND NOT ({trip_level})""")
        else:
            con.execute("""CREATE OR REPLACE TEMP TABLE cand_transfers (from_stop_id VARCHAR, to_stop_id VARCHAR,
                transfer_type INTEGER, min_transfer_time INTEGER)""")

        _write(con, out_dir, prefix, feed_id)
        report.stops_out = _count(con, "SELECT * FROM cand_stops")
        report.routes_out = _count(con, "SELECT * FROM n_routes WHERE route_id IN (SELECT route_id FROM cand_trips)")
        report.trips_out = _count(con, "SELECT * FROM cand_trips")
        report.stop_times_out = _count(con, "SELECT * FROM cand_st")
        report.service_dates_out = _count(con, "SELECT * FROM n_dates WHERE service_id IN (SELECT service_id FROM cand_trips)")
        report.transfers_out = _count(con, "SELECT * FROM cand_transfers")
        report.seconds = round((dt.datetime.now() - started).total_seconds(), 2)
        (out_dir / "report.json").write_text(json.dumps(asdict(report), ensure_ascii=False, indent=1), encoding="utf-8")
        return report

    try:
        last_error: Exception | None = None
        for encoding, parallel in CSV_MODES:
            try:
                return attempt(encoding, parallel)
            except (duckdb.Error, FeedError) as error:
                if isinstance(error, FeedError) and "is missing" in str(error):
                    raise  # another reading mode will not conjure a missing file
                last_error = error
        raise FeedError(f"unreadable in every CSV mode, last error: {last_error}")
    finally:
        if own:
            con.close()


def normalize_all(rows: list[dict], window: Window, sha256_by_feed: dict[str, str] | None = None,
                  force: bool = False, memory_limit: str = "6GB", progress=print) -> tuple[list[FeedReport], dict[str, str]]:
    """Normalize every row; a broken feed is reported, not fatal. Returns (reports, errors)."""
    sha256_by_feed = sha256_by_feed or {}
    reports, errors = [], {}
    con = connect(memory_limit)
    try:
        for i, row in enumerate(rows, 1):
            feed_id = row["feed_id"]
            try:
                report = normalize_feed(row, window, con, source_sha256=sha256_by_feed.get(feed_id, ""), force=force)
                reports.append(report)
                progress(f"[{i:>3}/{len(rows)}] {feed_id}: {report.trips_out} trips, {report.stops_out} stops ({report.seconds} s)")
            except Exception as error:  # one bad feed must not stop the other 200
                errors[feed_id] = f"{error.__class__.__name__}: {error}"
                progress(f"[{i:>3}/{len(rows)}] {feed_id}: FAILED {errors[feed_id]}")
    finally:
        con.close()
    return reports, errors


def _filter_agencies(agencies, keep: str, drop: str):
    """Kept agency ids, dropped agency names, and how many agencies the filter matched."""
    kept, dropped, matches = [], [], None
    keep_rx = re.compile(keep) if keep else None
    drop_rx = re.compile(drop) if drop else None
    if keep_rx or drop_rx:
        matches = 0
    for agency_id, name in agencies:
        name = name or ""
        hit_keep = keep_rx.search(name) if keep_rx else True
        hit_drop = drop_rx.search(name) if drop_rx else False
        if (keep_rx and hit_keep) or (drop_rx and hit_drop):
            matches += 1
        if hit_keep and not hit_drop:
            kept.append(agency_id)
        else:
            dropped.append(name)
    return kept, dropped, matches


def _service_dates(con, calendar_cols: set[str], dates_cols: set[str], window: Window) -> None:
    """n_dates(service_id, date): every date of the window each service runs on."""
    start, end = _sql_str(window.start.isoformat()), _sql_str(window.end.isoformat())
    con.execute(f"""CREATE OR REPLACE TEMP TABLE window_days AS
        SELECT CAST(d AS DATE) AS d FROM generate_series(CAST({start} AS DATE), CAST({end} AS DATE), INTERVAL 1 DAY) g(d)""")
    parts = []
    if {"service_id", "start_date", "end_date"} <= calendar_cols:
        days = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        flag = "CASE dayofweek(w.d) " + " ".join(
            f"WHEN {i} THEN {_col(calendar_cols, day, chr(39) + '0' + chr(39))}" for i, day in enumerate(days)) + " END"
        parts.append(f"""SELECT c.service_id, w.d FROM raw_calendar c JOIN window_days w
            ON w.d BETWEEN try_strptime(c.start_date, '%Y%m%d') AND try_strptime(c.end_date, '%Y%m%d')
            WHERE {flag} = '1'""")
    if {"service_id", "date", "exception_type"} <= dates_cols:
        parts.append("""SELECT service_id, CAST(try_strptime(date, '%Y%m%d') AS DATE) FROM raw_calendar_dates
            WHERE exception_type = '1' AND CAST(try_strptime(date, '%Y%m%d') AS DATE) IN (SELECT d FROM window_days)""")
        removed = """SELECT service_id, CAST(try_strptime(date, '%Y%m%d') AS DATE) FROM raw_calendar_dates WHERE exception_type = '2'"""
    else:
        removed = "SELECT NULL::VARCHAR, NULL::DATE WHERE false"
    union = " UNION ".join(parts) if parts else "SELECT NULL::VARCHAR, NULL::DATE WHERE false"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE n_dates AS
        SELECT DISTINCT service_id, d AS date FROM (({union}) EXCEPT ({removed})) x(service_id, d)
        WHERE service_id IS NOT NULL AND d IS NOT NULL""")


def _expand_frequencies(con, cols: set[str]) -> int:
    """Replace each frequency-based template trip by one trip per departure."""
    if not {"trip_id", "start_time", "end_time", "headway_secs"} <= cols:
        return 0
    con.execute(f"""CREATE OR REPLACE TEMP TABLE freq AS
        SELECT trip_id, {_time('start_time')} AS t_start, {_time('end_time')} AS t_end,
               TRY_CAST(headway_secs AS INTEGER) AS headway
        FROM raw_frequencies WHERE trip_id IN (SELECT trip_id FROM cand_trips)""")
    con.execute("DELETE FROM freq WHERE t_start IS NULL OR t_end IS NULL OR headway IS NULL OR headway <= 0 OR t_end <= t_start")
    if _count(con, "SELECT * FROM freq") == 0:
        return 0
    # end_time is exclusive: departures at start, start + headway, … while < end.
    con.execute("""CREATE OR REPLACE TEMP TABLE freq_runs AS
        SELECT trip_id, departure, trip_id || '@' || CAST(departure AS VARCHAR) AS new_trip_id
        FROM (SELECT trip_id, unnest(generate_series(t_start, t_end - 1, headway)) AS departure FROM freq)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE freq_first AS
        SELECT trip_id, arg_min(coalesce(dep, arr), seq) AS t0
        FROM cand_st WHERE trip_id IN (SELECT trip_id FROM freq) GROUP BY trip_id""")
    con.execute("""INSERT INTO cand_st
        SELECT r.new_trip_id, s.stop_id, s.seq, s.arr + (r.departure - f.t0), s.dep + (r.departure - f.t0)
        FROM freq_runs r JOIN cand_st s ON s.trip_id = r.trip_id JOIN freq_first f ON f.trip_id = r.trip_id
        WHERE f.t0 IS NOT NULL""")
    con.execute("""INSERT INTO cand_trips
        SELECT r.new_trip_id, t.route_id, t.service_id, t.direction_id
        FROM freq_runs r JOIN cand_trips t ON t.trip_id = r.trip_id
        WHERE r.trip_id IN (SELECT trip_id FROM freq_first WHERE t0 IS NOT NULL)""")
    templates = "SELECT trip_id FROM freq"
    con.execute(f"DELETE FROM cand_st WHERE trip_id IN ({templates})")
    con.execute(f"DELETE FROM cand_trips WHERE trip_id IN ({templates})")
    return _count(con, "SELECT * FROM freq_runs")


def _interpolate(con) -> tuple[int, int]:
    """Fill missing times along each trip's distance. Returns (filled, trips dropped)."""
    con.execute("UPDATE cand_st SET arr = coalesce(arr, dep), dep = coalesce(dep, arr) WHERE arr IS NULL OR dep IS NULL")
    missing = _count(con, "SELECT * FROM cand_st WHERE arr IS NULL")
    if missing == 0:
        return 0, 0
    con.execute("""CREATE OR REPLACE TEMP TABLE st_pos AS
        SELECT s.*, sum(coalesce(hop, 0)) OVER (PARTITION BY s.trip_id ORDER BY s.seq) AS cum
        FROM (SELECT st.*, 6371000 * 2 * asin(sqrt(
                    power(sin(radians(p.lat - lag(p.lat) OVER w) / 2), 2) +
                    cos(radians(p.lat)) * cos(radians(lag(p.lat) OVER w)) *
                    power(sin(radians(p.lon - lag(p.lon) OVER w) / 2), 2))) AS hop
              FROM cand_st st JOIN cand_stops p USING (stop_id)
              WINDOW w AS (PARTITION BY st.trip_id ORDER BY st.seq)) s
        WHERE s.trip_id IN (SELECT DISTINCT trip_id FROM cand_st WHERE arr IS NULL)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE st_fill AS
        SELECT trip_id, seq,
               CAST(round(prev_t + (next_t - prev_t) * CASE WHEN next_c > prev_c THEN (cum - prev_c) / (next_c - prev_c)
                                                           ELSE (seq - prev_s) / (next_s - prev_s) END) AS INTEGER) AS t
        FROM (SELECT *,
                last_value(CASE WHEN arr IS NOT NULL THEN dep END IGNORE NULLS) OVER wp AS prev_t,
                last_value(CASE WHEN arr IS NOT NULL THEN cum END IGNORE NULLS) OVER wp AS prev_c,
                last_value(CASE WHEN arr IS NOT NULL THEN seq END IGNORE NULLS) OVER wp AS prev_s,
                first_value(CASE WHEN arr IS NOT NULL THEN arr END IGNORE NULLS) OVER wn AS next_t,
                first_value(CASE WHEN arr IS NOT NULL THEN cum END IGNORE NULLS) OVER wn AS next_c,
                first_value(CASE WHEN arr IS NOT NULL THEN seq END IGNORE NULLS) OVER wn AS next_s
              FROM st_pos
              WINDOW wp AS (PARTITION BY trip_id ORDER BY seq ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
                     wn AS (PARTITION BY trip_id ORDER BY seq ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING))
        WHERE arr IS NULL AND prev_t IS NOT NULL AND next_t IS NOT NULL""")
    con.execute("""UPDATE cand_st SET arr = f.t, dep = f.t FROM st_fill f
        WHERE cand_st.trip_id = f.trip_id AND cand_st.seq = f.seq""")
    filled = _count(con, "SELECT * FROM st_fill")
    # Whatever is still missing sits before the first or after the last known time.
    broken = "SELECT DISTINCT trip_id FROM cand_st WHERE arr IS NULL"
    dropped = _count(con, broken)
    con.execute(f"DELETE FROM cand_trips WHERE trip_id IN ({broken})")
    con.execute("DELETE FROM cand_st WHERE trip_id NOT IN (SELECT trip_id FROM cand_trips)")
    return filled, dropped


def _write(con, out_dir: Path, prefix: str, feed_id: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = prefix
    queries = {
        "agency": f"""SELECT {p} || agency_id AS agency_id, agency_name, agency_url, agency_lang FROM n_agency
                     WHERE agency_id IN (SELECT agency_id FROM n_routes WHERE route_id IN (SELECT route_id FROM cand_trips))""",
        "stops": f"""SELECT {p} || stop_id AS stop_id, stop_name, lat, lon,
                        CASE WHEN zone_id IS NULL THEN NULL ELSE {p} || zone_id END AS zone_id, {_sql_str(feed_id)} AS feed_id
                     FROM cand_stops WHERE stop_id IN (SELECT stop_id FROM cand_st)""",
        "routes": f"""SELECT {p} || route_id AS route_id, {p} || agency_id AS agency_id, route_short_name, route_long_name,
                        route_type, route_color, route_text_color FROM n_routes WHERE route_id IN (SELECT route_id FROM cand_trips)""",
        "trips": f"""SELECT {p} || trip_id AS trip_id, {p} || route_id AS route_id, {p} || service_id AS service_id,
                        direction_id, {_sql_str(feed_id)} AS feed_id FROM cand_trips""",
        "stop_times": f"""SELECT {p} || trip_id AS trip_id, {p} || stop_id AS stop_id, seq AS stop_sequence,
                        arr AS arrival_time, dep AS departure_time FROM cand_st""",
        "calendar_dates": f"""SELECT {p} || service_id AS service_id, date FROM n_dates
                        WHERE service_id IN (SELECT service_id FROM cand_trips)""",
        "transfers": f"""SELECT {p} || from_stop_id AS from_stop_id, {p} || to_stop_id AS to_stop_id, transfer_type,
                        min_transfer_time FROM cand_transfers
                        WHERE from_stop_id IN (SELECT stop_id FROM cand_st) AND to_stop_id IN (SELECT stop_id FROM cand_st)""",
    }
    for table, query in queries.items():
        target = (out_dir / f"{table}.parquet").as_posix()
        con.execute(f"COPY ({query}) TO {_sql_str(target)} (FORMAT parquet, COMPRESSION zstd)")
