"""Which lines are school lines: the list the explorer's "lignes scolaires" switch hides.

GTFS has no school flag. A line (a route of a normalized feed) counts as a school line when
one of these rules says so, checked in this order; the first that matches is the one recorded:

- feed:       the whole feed is school transport (catalogue `school` = all);
- route_type: 712 (school bus) or 713 (school and public service bus), GTFS extended types,
              which TCL (its JD lines), the Grand Est aggregate or Puy-de-Dôme use;
- name:       the name says so: "ligne scolaire", "services scolaires", "Scolaire S35", or a
              short name starting with "sco";
- feed rule:  the feed's own convention, a regex on the short name in the catalogue `school`
              column (Rennes STAR: Ts30, Ts44…);
- few runs:   the line serves a school (collège, lycée, école, cité or groupe scolaire in its
              long name) and runs at most FEW_RUNS trips on the reference day, both ways. A line
              that merely ends at a lycée runs all day; a school run comes once or twice each way.

The result is one row per line in results/school_routes.csv, with the rule and the trips on
the reference day, for review. A merged tier keeps the ids (with "~k" for the extra stop
patterns of a line), so `engine_route_ids` maps the list onto the route numbers raptor-kmp
gets from the pipeline: the row order of the merged routes.txt.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

from .normalize import NORMALIZED_DIR

FEW_RUNS = 6
SCHOOL_ROUTE_TYPES = (712, 713)
NAME = re.compile(r"\b(lignes?|circuits?|services?|transports?|dessertes?|navettes?) scolaires?\b|^scolaire\b")
SHORT_NAME = re.compile(r"^sco", re.IGNORECASE)
SERVES_SCHOOL = re.compile(r"coll[eè]ge|lyc[ée]e|[ée]cole|cit[ée] scolaire|groupe scolaire|\blep\b", re.IGNORECASE)
RULES = ("feed", "route_type", "name", "feed rule", "few runs")
FILE = "school_routes.json"


def _feed_rule(value: str) -> re.Pattern | None:
    value = (value or "").strip()
    return None if value in ("", "all") else re.compile(value)


def classify(route: dict, feed_school: str, trips_on_day: int, few_runs: int = FEW_RUNS) -> str | None:
    """The rule that makes this line a school line, or None."""
    short, long = route.get("route_short_name") or "", route.get("route_long_name") or ""
    if (feed_school or "").strip() == "all":
        return "feed"
    if route.get("route_type") in SCHOOL_ROUTE_TYPES:
        return "route_type"
    if NAME.search(f"{short} {long}".lower()) or NAME.search(long.lower()) or SHORT_NAME.match(short):
        return "name"
    rule = _feed_rule(feed_school)
    if rule is not None and rule.search(short):
        return "feed rule"
    if SERVES_SCHOOL.search(long) and trips_on_day <= few_runs:
        return "few runs"
    return None


def school_routes(rows: list[dict], reference: dt.date, normalized_dir: Path = NORMALIZED_DIR,
                  few_runs: int = FEW_RUNS) -> pd.DataFrame:
    """Every line of the rows' normalized feeds, with its trips on `reference` and its rule
    (None for an ordinary line)."""
    frames = []
    con = duckdb.connect()
    try:
        for row in rows:
            folder = normalized_dir / row["feed_id"]
            if not (folder / "routes.parquet").exists():
                continue
            frame = con.execute(f"""
                SELECT r.route_id, r.route_short_name, r.route_long_name, r.route_type,
                       count(DISTINCT t.trip_id) FILTER (WHERE d.date = DATE '{reference.isoformat()}') AS trips_on_day
                FROM read_parquet('{(folder / 'routes.parquet').as_posix()}') r
                LEFT JOIN read_parquet('{(folder / 'trips.parquet').as_posix()}') t USING (route_id)
                LEFT JOIN read_parquet('{(folder / 'calendar_dates.parquet').as_posix()}') d USING (service_id)
                GROUP BY ALL""").df()
            frame.insert(0, "feed_id", row["feed_id"])
            frame["feed_school"] = row.get("school", "") or ""
            frames.append(frame)
    finally:
        con.close()
    if not frames:
        return pd.DataFrame(columns=["feed_id", "route_id", "route_short_name", "route_long_name", "route_type",
                                     "trips_on_day", "rule"])
    lines = pd.concat(frames, ignore_index=True)
    lines["trips_on_day"] = lines["trips_on_day"].fillna(0).astype(int)
    lines["route_type"] = lines["route_type"].fillna(3).astype(int)
    for column in ("route_short_name", "route_long_name"):
        lines[column] = lines[column].fillna("")
    lines["rule"] = [classify(r, r["feed_school"], r["trips_on_day"], few_runs) for r in lines.to_dict("records")]
    return lines.drop(columns="feed_school")


def summary(lines: pd.DataFrame) -> pd.DataFrame:
    """Per feed: lines, school lines by rule, trips on the day and the school share."""
    school = lines[lines["rule"].notna()]
    table = lines.groupby("feed_id").agg(lines=("route_id", "size"), trips_on_day=("trips_on_day", "sum"))
    by_rule = school.pivot_table(index="feed_id", columns="rule", values="route_id", aggfunc="size", fill_value=0)
    table = table.join(by_rule, how="left").fillna(0)
    table["school_lines"] = school.groupby("feed_id").size()
    table["school_trips"] = school.groupby("feed_id")["trips_on_day"].sum()
    table = table.fillna(0)
    for column in [c for c in table.columns if c != "feed_id"]:
        table[column] = table[column].astype(int)
    return table[table["school_lines"] > 0].sort_values("school_lines", ascending=False).reset_index()


def write_review(lines: pd.DataFrame, path: Path) -> None:
    """The school lines only, for review: feed, line, names, type, trips on the day, rule."""
    school = lines[lines["rule"].notna()].sort_values(["feed_id", "rule", "route_short_name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    school.to_csv(path, index=False, encoding="utf-8")


def engine_route_ids(merged_zip: Path, school_ids: set[str]) -> tuple[list[int], list[tuple[int, str]]]:
    """Route numbers raptor-kmp will know the school lines by.

    The pipeline numbers routes by their row in routes.txt (GTFSReader.readRoutes), and the
    engine's Route.id is that number. A merged route id is a normalized one, plus "~k" for
    the extra stop patterns of a line (merge.split_patterns). Returns the numbers, and (number,
    name) pairs to check against the engine's own list.
    """
    with zipfile.ZipFile(merged_zip) as archive, archive.open("routes.txt") as handle:
        reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))
        ids, names = [], []
        for index, row in enumerate(reader):
            if row["route_id"].split("~", 1)[0] in school_ids:
                ids.append(index)
                names.append((index, row.get("route_short_name") or row.get("route_long_name") or ""))
    return ids, names


def write_engine_file(data_dir: Path, route_ids: list[int], lines: pd.DataFrame, reference: dt.date) -> Path:
    """data_dir/school_routes.json: what the engine server loads to hide the school lines."""
    school = lines[lines["rule"].notna()]
    payload = {
        "reference_date": reference.isoformat(),
        "routeIds": route_ids,
        "lines": int(len(school)),
        "by_rule": {rule: int((school["rule"] == rule).sum()) for rule in RULES},
        "trips_on_day": int(school["trips_on_day"].sum()),
    }
    path = data_dir / FILE
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path
