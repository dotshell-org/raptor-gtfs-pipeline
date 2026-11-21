"""Daily refresh: fetch the feeds, move the window forward, rebuild the live France network.

    python -m gtfs_bench.refresh             # what the daily task runs (refresh.ps1)
    python -m gtfs_bench.refresh --force     # rebuild even if nothing changed
    python -m gtfs_bench.refresh --no-build  # download and report only

Producers publish a few weeks ahead (IDFM about a month) and replace their files as they go,
so a network that keeps every current feed covers weeks, not months, and stays ahead only if
it is rebuilt as the files change. Each run:

1. downloads every included feed of the three layers (conditional requests: an unchanged
   file costs one round trip);
2. asks the PAN for newer resources of the feeds about to stop (a ski shuttle's winter
   timetable, next year's file): they are reported, not added, the catalogue stays curated;
3. computes the horizon, the window and the day types (gtfs_bench.horizon);
4. rebuilds data/raptor/france-live when a feed changed or the day types moved: merge as
   france-complete, pipeline with one period per day type, school lines per period. It is
   built next to the live one and swapped in at the end, so the explorer never reads half
   a network;
5. writes its log to data/logs/refresh-<date>.log and what it did to
   data/raptor/france-live/refresh.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

from . import school as school_lines
from .catalog import fetch_candidates, read_catalog
from .convert import DATA_DIR, MERGED_DIR, RAPTOR_DIR, convert_tier, write_day_types_profile
from .download import EXTRACTED_DIR, RAW_DIR, download_all, extract_feed, read_manifest, write_manifest
from .horizon import LAYERS, Plan, plan as make_plan, write_results
from .merge import MergeParams, Tier, merge_tier
from .normalize import Window, normalize_all
from .settings import load as load_settings

LIVE_KEY = "france-live"
LIVE_DIR = RAPTOR_DIR / LIVE_KEY
LOG_DIR = DATA_DIR / "logs"
SOON_DAYS = 35


SIGNATURES = RAW_DIR / "content_signatures.json"


def content_signature(zip_path: Path) -> str:
    """The files of a feed's zip (name, size, CRC-32), not the zip's own bytes: a server that
    rebuilds the same feed at each request gives the same signature."""
    import hashlib
    import zipfile

    try:
        with zipfile.ZipFile(zip_path) as archive:
            entries = sorted((i.filename, i.file_size, i.CRC) for i in archive.infolist() if not i.is_dir())
    except (OSError, zipfile.BadZipFile):
        return ""
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()[:20]


def _read_signatures() -> dict[str, str]:
    return json.loads(SIGNATURES.read_text(encoding="utf-8")) if SIGNATURES.exists() else {}


def _write_signatures(signatures: dict[str, str]) -> None:
    SIGNATURES.write_text(json.dumps(signatures, indent=0, sort_keys=True), encoding="utf-8")


def live_rows() -> list[dict]:
    return [r for r in read_catalog() if r["include"] and r["layer"] in LAYERS]


def prepare(rows: list[dict], window: Window, progress=print, download: bool = True) -> list[dict]:
    """Download what is missing (unless told not to) and normalize, both cached: returns the
    rows ready to merge. (It lived in gtfs_bench.connected, with the benchmark's variants.)"""
    manifest = read_manifest()
    missing = [r for r in rows if r["feed_id"] not in manifest or not manifest[r["feed_id"]].ok]
    if missing and download:
        download_all(missing, progress=lambda line: None)
        manifest = read_manifest()
    _, errors = normalize_all(rows, window, {k: m.sha256 for k, m in manifest.items()}, progress=lambda line: None)
    for feed_id, error in errors.items():
        progress(f"  normalization FAILED {feed_id}: {error[:200]}")
    return [r for r in rows if r["feed_id"] not in errors and manifest.get(r["feed_id"]) and manifest[r["feed_id"]].ok]


def successors(rows: list[dict], table, today: dt.date, candidates: list[dict] | None = None,
               soon_days: int = SOON_DAYS) -> list[dict]:
    """Valid PAN resources, not in the catalogue, of the datasets whose feed stops within soon_days."""
    soon = {r.feed_id: r.last_day.date() for r in table.itertuples()
            if r.first_week_trips > 0 and r.last_day.date() <= today + dt.timedelta(days=soon_days)}
    by_feed = {r["feed_id"]: r for r in rows}
    catalogued = {str(r.get("pan_resource_id", "")) for r in read_catalog()}
    candidates = candidates if candidates is not None else fetch_candidates(today)
    found = []
    for feed_id, last in sorted(soon.items(), key=lambda kv: kv[1]):
        dataset = by_feed.get(feed_id, {}).get("pan_dataset_id")
        for c in candidates:
            if (dataset and c["pan_dataset_id"] == dataset and str(c["pan_resource_id"]) not in catalogued
                    and c["status"] == "ok" and (c.get("end_date") or "") > last.isoformat()):
                found.append({"feed_id": feed_id, "stops_on": last.isoformat(), "pan_resource_id": c["pan_resource_id"],
                              "title": c.get("resource_title"), "start_date": c.get("start_date"), "end_date": c.get("end_date"),
                              "url": c.get("url")})
    return found


def build_live(result: Plan, rows: list[dict], java: str | None = None, xmx: str | None = None, out_dir: Path = LIVE_DIR,
               progress=print, download: bool = True) -> dict:
    """Merge, convert with one period per day type, tag school lines; swap in at the end.
    Heap, transfer and station parameters come from settings.json (gtfs_bench.settings)."""
    settings = load_settings()
    xmx = xmx or settings.engine.pipeline_xmx
    days = {name: dt.date.fromisoformat(day) for name, day in result.days.items()}
    main = dt.date.fromisoformat(result.days["semaine"])
    ready = prepare(rows, result.normalization_window(), progress, download)
    tier = Tier(LIVE_KEY, "france", "France complète, fenêtre glissante", tuple(ready), area_code="mainland")
    params = MergeParams(reference_date=main, transfers=settings.merge.transfer_params(), split_patterns=True,
                         stations=settings.merge.station_params(), name_radius_m=settings.merge.name_radius_m,
                         memory_limit=settings.merge.duckdb_memory)
    report = merge_tier(tier, params, out_dir=MERGED_DIR / "variants", progress=progress)
    zip_path = MERGED_DIR / "variants" / "france" / f"{LIVE_KEY}.zip"
    building = out_dir.with_name(out_dir.name + ".new")
    profile = write_day_types_profile(days, DATA_DIR / "profiles" / f"{LIVE_KEY}.yaml")
    conversion = convert_tier(zip_path, building, profile, xmx, java, period="semaine")
    if conversion.status != "ok":
        raise RuntimeError(f"pipeline {conversion.status}: {conversion.error}")
    lines = school_lines.school_routes(ready, main, few_runs=settings.school.few_runs)
    route_ids, _ = school_lines.engine_route_ids(zip_path, set(lines.loc[lines["rule"].notna(), "route_id"]))
    for name in days:
        school_lines.write_engine_file(building / name, route_ids, lines, main)
    (building / "horizon.json").write_text(result.to_json(), encoding="utf-8")
    old = out_dir.with_name(out_dir.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if out_dir.exists():
        out_dir.rename(old)
    building.rename(out_dir)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    periods = conversion.extra.get("periods", {})
    progress(f"{LIVE_KEY}: {len(ready)} feeds, pipeline {conversion.seconds} s, peak {conversion.peak_memory_mb} MB, "
             + ", ".join(f"{n} {s.get('trips')} trips" for n, s in periods.items()))
    return {"feeds": len(ready), "merge_seconds": report.seconds, "pipeline_seconds": conversion.seconds,
            "pipeline_peak_mb": conversion.peak_memory_mb, "periods": periods,
            "school_route_ids": len(route_ids)}


def refresh(today: dt.date | None = None, force: bool = False, build: bool = True, java: str | None = None,
            check_pan: bool = True, progress=print, download: bool = True) -> dict:
    """`download=False` builds from the zips already in data/raw (and their manifest)."""
    today = today or dt.date.today()
    started = time.perf_counter()
    rows = live_rows()
    progress(f"refresh {today}: {len(rows)} feeds" + ("" if download else ", from the zips already here"))

    before = read_manifest()
    if download:
        results = download_all(rows, progress=lambda line: None)
        ok = [r.feed_id for r in results if r.ok]
        failed = sorted(r.feed_id for r in results if not r.ok)
    else:
        ok = [r["feed_id"] for r in rows if r["feed_id"] in before and before[r["feed_id"]].ok]
        failed = []
        for feed_id in ok:  # zips copied in from elsewhere: unpacked as a download would
            if not (EXTRACTED_DIR / feed_id / "stops.txt").exists():
                extract_feed(RAW_DIR / f"{feed_id}.zip", EXTRACTED_DIR / feed_id)
    # Many servers ignore conditional requests, and some build the zip afresh at each request
    # (new timestamps, new sha256, same timetables): what counts is the files inside.
    signatures = _read_signatures()
    now = {f: content_signature(RAW_DIR / f"{f}.zip") for f in ok}
    changed = sorted(f for f, sig in now.items() if sig and signatures.get(f) != sig)
    _write_signatures({**signatures, **{f: s for f, s in now.items() if s}})
    # A feed that fails today (server down, timeout) keeps yesterday's file rather than
    # dropping out of the network: its last good manifest entry goes back.
    kept = {f: before[f] for f in failed if f in before and before[f].ok and (RAW_DIR / f"{f}.zip").exists()}
    if kept:
        write_manifest({**read_manifest(), **kept})
    progress(f"download: {len(changed)} changed" + (f" ({', '.join(changed)})" if 0 < len(changed) <= 10 else "")
             + f", {len(failed)} failed" + (f" ({', '.join(failed)})" if failed else "")
             + (f", {len(kept)} of them kept from their last good download" if kept else ""))

    live = load_settings().live
    result, table, days = make_plan(rows, today, live.max_feed_share, live.max_lost_share)
    write_results(result, table, days)
    progress(f"window {result.start} → {result.end} (stops with {result.binding_feed}), days {result.days}, "
             f"{len(result.lost)} small feeds stop earlier")

    found = []
    if check_pan:
        try:
            found = successors(rows, table, today, soon_days=live.soon_days)
        except Exception as error:  # the PAN being down must not stop the refresh
            progress(f"PAN check failed: {error}")
    if check_pan and not found:
        progress(f"PAN: no newer resource for the feeds that stop within {SOON_DAYS} days")
    for s in found:
        progress(f"newer resource for {s['feed_id']} (stops {s['stops_on']}): {s['pan_resource_id']} "
                 f"{s['title']!r} {s['start_date']} → {s['end_date']}")

    previous = Plan.read(LIVE_DIR / "horizon.json") if (LIVE_DIR / "horizon.json").exists() else None
    reasons = []
    if previous is None:
        reasons.append("no live network yet")
    elif previous.days != result.days:
        reasons.append(f"day types moved: {previous.days} → {result.days}")
    if changed:
        reasons.append(f"{len(changed)} feeds changed")
    if force:
        reasons.append("forced")
    built = None
    if build and reasons:
        progress("rebuilding: " + "; ".join(reasons))
        built = build_live(result, rows, java, progress=progress, download=download)
    elif build:
        (LIVE_DIR / "horizon.json").write_text(result.to_json(), encoding="utf-8")  # same network, window moved on
        progress("nothing changed: the live network stays as it is")

    summary = {"date": today.isoformat(), "seconds": round(time.perf_counter() - started, 1), "changed": changed,
               "failed": failed, "window": [result.start, result.end], "binding_feed": result.binding_feed,
               "days": result.days, "lost": result.lost, "successors": found, "rebuilt": bool(built),
               "reasons": reasons, "build": built}
    if LIVE_DIR.exists():
        (LIVE_DIR / "refresh.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.refresh", description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even if nothing changed")
    parser.add_argument("--no-build", action="store_true", help="download and report only")
    parser.add_argument("--no-pan", action="store_true", help="skip the check for newer PAN resources")
    parser.add_argument("--no-download", action="store_true", help="build from the zips already in data/raw")
    parser.add_argument("--today", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    args = parser.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"refresh-{today.isoformat()}.log"
    with log_path.open("a", encoding="utf-8") as log:
        def progress(line: str) -> None:
            stamped = f"{dt.datetime.now():%H:%M:%S} {line}"
            print(stamped, flush=True)
            log.write(stamped + "\n")
            log.flush()
        try:
            refresh(today, args.force, not args.no_build, args.java, not args.no_pan, progress, not args.no_download)
        except Exception as error:
            progress(f"FAILED: {error!r}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
