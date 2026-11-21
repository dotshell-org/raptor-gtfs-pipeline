"""How far ahead the feeds go, and the window and day types a rolling France network can cover.

    python -m gtfs_bench.horizon            # today's horizon: data/results/feed_horizon.csv, horizon.json

raptor-kmp has no calendar: a network is one day's timetable. Pelo serves TCL with a few
day types (school weekday, holiday weekday, Saturday, Sunday) cut from a feed that covers
months. For France the window is the stretch where the feeds still publish timetables, and
the day types are taken from it:

1. **Trips per day and feed**, from each feed's own calendar (normalize.trips_per_day), from
   today on. Cached per feed by its sha256: a feed that did not change is not read again.
2. **The window** starts today. It ends the day before the first feed that matters stops:
   a feed carrying more than `max_feed_share` of the trips, or the one that takes the feeds
   already stopped past `max_lost_share` together (shares of the first week's trips). Small
   feeds (a ski shuttle between two seasons) may stop earlier: they are listed as lost.
3. **Day types**: one representative day each, a Tuesday, a Saturday and a Sunday of the
   same week, the earliest week inside the window whose three days are all ahead, not public
   holidays, and the Tuesday outside the national school holidays. A fourth, `vacances`, is a
   holiday Tuesday when the window reaches national school holidays.
4. **A date's network**: Sunday or public holiday → dimanche; Saturday → samedi; a weekday
   in national school holidays → vacances (when there is one), else semaine.

Only the national school holidays (Christmas and summer) are known here: the winter and
spring ones differ by zone, and a single France network cannot follow three calendars.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .catalog import read_catalog
from .convert import DATA_DIR, RESULTS_DIR
from .download import read_manifest
from .normalize import Window, connect, trips_per_day

CACHE_DIR = DATA_DIR / "tmp" / "horizon"
LAYERS = ("regional", "longue_distance", "scolaire")
MAX_FEED_SHARE = 0.005
MAX_LOST_SHARE = 0.01
HORIZON_DAYS = 300
#: National school holidays (every zone at once), 2026–2027 calendar.
SCHOOL_HOLIDAYS = ((dt.date(2026, 12, 19), dt.date(2027, 1, 3)), (dt.date(2027, 7, 3), dt.date(2027, 8, 31)))
DAY_TYPES = ("semaine", "samedi", "dimanche", "vacances")
LABELS = {"semaine": "semaine", "samedi": "samedi", "dimanche": "dimanche et fêtes", "vacances": "vacances scolaires"}


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    return dt.date(year, month, (h + l - 7 * m + 33 * month + 19) % 32)


def public_holidays(year: int) -> set[dt.date]:
    """The 11 public holidays of mainland France."""
    e = easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    return {dt.date(year, m, d) for m, d in fixed} | {e + dt.timedelta(days=1), e + dt.timedelta(days=39),
                                                     e + dt.timedelta(days=50)}


def is_public_holiday(day: dt.date) -> bool:
    return day in public_holidays(day.year)


def in_school_holidays(day: dt.date, holidays=SCHOOL_HOLIDAYS) -> bool:
    return any(start <= day <= end for start, end in holidays)


def day_type(day: dt.date, has_vacances: bool, holidays=SCHOOL_HOLIDAYS) -> str:
    """Which day type's network serves this date (Pelo's rule: public holidays run as Sundays)."""
    if day.weekday() == 6 or is_public_holiday(day):
        return "dimanche"
    if day.weekday() == 5:
        return "samedi"
    if has_vacances and in_school_holidays(day, holidays):
        return "vacances"
    return "semaine"


# ── trips per day ────────────────────────────────────────────────────────────────────


def feed_days(rows: list[dict], start: dt.date, days: int = HORIZON_DAYS, cache_dir: Path = CACHE_DIR,
              progress=lambda s: None) -> pd.DataFrame:
    """(feed_id, date, trips) for every row from `start` on, from the extracted feeds.

    A feed's counts are cached under its sha256 (manifest): they depend only on the file, so
    a later run reads them back as long as they cover the days asked for.
    """
    manifest = read_manifest()
    end = start + dt.timedelta(days=days - 1)
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames, con = [], connect()
    try:
        for row in rows:
            feed_id = row["feed_id"]
            sha = manifest[feed_id].sha256 if feed_id in manifest else ""
            meta_path, data_path = cache_dir / f"{feed_id}.json", cache_dir / f"{feed_id}.parquet"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            if (sha and meta.get("sha256") == sha and meta.get("start") <= start.isoformat()
                    and meta.get("end") >= end.isoformat() and data_path.exists()):
                frame = pd.read_parquet(data_path)
            else:
                try:
                    frame = trips_per_day(row, Window(start - dt.timedelta(days=7), end), con)
                except Exception as error:  # an unreadable feed counts as no service, and says so
                    progress(f"  {feed_id}: {str(error)[:120]}")
                    frame = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "trips": pd.Series(dtype="int64")})
                frame["date"] = pd.to_datetime(frame["date"])
                frame.to_parquet(data_path, index=False)
                meta_path.write_text(json.dumps({"sha256": sha, "start": (start - dt.timedelta(days=7)).isoformat(),
                                                 "end": end.isoformat()}), encoding="utf-8")
            frame = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))].copy()
            frame.insert(0, "feed_id", feed_id)
            frames.append(frame)
    finally:
        con.close()
    days_table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["feed_id", "date", "trips"])
    days_table["trips"] = days_table["trips"].astype(int)
    return days_table


# ── window and day types ─────────────────────────────────────────────────────────────


@dataclass
class Plan:
    computed_on: str
    start: str
    end: str
    binding_feed: str | None
    binding_share: float | None
    days: dict[str, str]                              # day type -> representative date
    lost: list[dict] = field(default_factory=list)    # small feeds that stop inside the window
    feeds: int = 0                                    # feeds running in the first week
    max_feed_share: float = MAX_FEED_SHARE
    max_lost_share: float = MAX_LOST_SHARE

    @property
    def window(self) -> tuple[dt.date, dt.date]:
        return dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)

    def normalization_window(self) -> Window:
        """Every representative day, in whole weeks: the merge and the pipeline read only those."""
        dates = [dt.date.fromisoformat(d) for d in self.days.values()]
        first, last = min(dates), max(dates)
        return Window(first - dt.timedelta(days=first.weekday()), last + dt.timedelta(days=6 - last.weekday()))

    def network_for(self, day: dt.date) -> str | None:
        """The day type serving `day`, or None outside the window."""
        start, end = self.window
        if not start <= day <= end:
            return None
        return day_type(day, "vacances" in self.days)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def read(cls, path: Path) -> Plan:
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def feed_table(days: pd.DataFrame, start: dt.date) -> pd.DataFrame:
    """Per feed: first and last day with trips, its trips over the first week and their share."""
    week_end = pd.Timestamp(start + dt.timedelta(days=6))
    running = days[days["trips"] > 0]
    table = running.groupby("feed_id")["date"].agg(first_day="min", last_day="max")
    week = running[running["date"] <= week_end].groupby("feed_id")["trips"].sum().rename("first_week_trips")
    table = table.join(week, how="outer").fillna({"first_week_trips": 0})
    table["first_week_trips"] = table["first_week_trips"].astype(int)
    table["share"] = table["first_week_trips"] / max(int(table["first_week_trips"].sum()), 1)
    return table.reset_index().sort_values(["last_day", "feed_id"])


def choose_window(table: pd.DataFrame, start: dt.date, max_feed_share: float = MAX_FEED_SHARE,
                  max_lost_share: float = MAX_LOST_SHARE, horizon_days: int = HORIZON_DAYS) -> tuple[dt.date, dict | None, list[dict]]:
    """The window's last day, the feed that sets it, and the small feeds lost before it."""
    current = table[table["first_week_trips"] > 0].sort_values("last_day")
    lost, lost_share = [], 0.0
    for row in current.itertuples():
        last = row.last_day.date()
        if lost_share + row.share > max_lost_share or row.share > max_feed_share:
            return last, {"feed_id": row.feed_id, "share": round(row.share, 5), "last_day": last.isoformat()}, lost
        lost_share += row.share
        lost.append({"feed_id": row.feed_id, "share": round(row.share, 5), "last_day": last.isoformat()})
    return start + dt.timedelta(days=horizon_days - 1), None, lost


def choose_days(days: pd.DataFrame, start: dt.date, end: dt.date, holidays=SCHOOL_HOLIDAYS) -> dict[str, dt.date]:
    """Representative days: Tuesday, Saturday and Sunday of the earliest week that fits, then a
    holiday Tuesday if the window reaches national school holidays."""
    feeds_on = days[days["trips"] > 0].groupby("date")["feed_id"].nunique()

    def ok(day: dt.date) -> bool:
        return start <= day <= end and not is_public_holiday(day)

    chosen: dict[str, dt.date] = {}
    monday = start - dt.timedelta(days=start.weekday())
    while monday <= end:
        tuesday, saturday, sunday = (monday + dt.timedelta(days=k) for k in (1, 5, 6))
        if all(ok(d) for d in (tuesday, saturday, sunday)) and not in_school_holidays(tuesday, holidays):
            chosen = {"semaine": tuesday, "samedi": saturday, "dimanche": sunday}
            break
        monday += dt.timedelta(days=7)
    if not chosen:
        raise ValueError(f"no week with a Tuesday, a Saturday and a Sunday between {start} and {end}")
    holiday_tuesdays = [d for d in pd.date_range(start, end).date
                        if d.weekday() == 1 and ok(d) and in_school_holidays(d, holidays)]
    if holiday_tuesdays:
        chosen["vacances"] = max(holiday_tuesdays, key=lambda d: (feeds_on.get(pd.Timestamp(d), 0), -d.toordinal()))
    return chosen


def plan(rows: list[dict], today: dt.date, max_feed_share: float = MAX_FEED_SHARE, max_lost_share: float = MAX_LOST_SHARE,
         days: pd.DataFrame | None = None, progress=lambda s: None) -> tuple[Plan, pd.DataFrame, pd.DataFrame]:
    """Today's window and day types. Returns the plan, the feed table and the trips per day."""
    days = days if days is not None else feed_days(rows, today, progress=progress)
    table = feed_table(days, today)
    end, binding, lost = choose_window(table, today, max_feed_share, max_lost_share)
    chosen = choose_days(days, today, end)
    result = Plan(computed_on=today.isoformat(), start=today.isoformat(), end=end.isoformat(),
                  binding_feed=binding["feed_id"] if binding else None, binding_share=binding["share"] if binding else None,
                  days={k: v.isoformat() for k, v in chosen.items()}, lost=lost,
                  feeds=int((table["first_week_trips"] > 0).sum()), max_feed_share=max_feed_share,
                  max_lost_share=max_lost_share)
    return result, table, days


# ── outputs ──────────────────────────────────────────────────────────────────────────


def write_results(result: Plan, table: pd.DataFrame, days: pd.DataFrame, results_dir: Path = RESULTS_DIR) -> dict:
    out = table.copy()
    for column in ("first_day", "last_day"):
        out[column] = out[column].dt.date
    out["share"] = out["share"].round(5)
    results_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(results_dir / "feed_horizon.csv", index=False)
    (results_dir / "horizon.json").write_text(result.to_json(), encoding="utf-8")
    return {"feeds": results_dir / "feed_horizon.csv", "plan": results_dir / "horizon.json"}


def included_rows(layers: tuple[str, ...] = LAYERS) -> list[dict]:
    return [r for r in read_catalog() if r["include"] and r["layer"] in layers]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.horizon", description=__doc__.splitlines()[0])
    parser.add_argument("--today", help="YYYY-MM-DD (default: today)")
    from .settings import load
    live = load().live
    parser.add_argument("--max-feed-share", type=float, default=live.max_feed_share)
    parser.add_argument("--max-lost-share", type=float, default=live.max_lost_share)
    args = parser.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    result, table, days = plan(included_rows(), today, args.max_feed_share, args.max_lost_share, progress=print)
    write_results(result, table, days)
    print(result.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
