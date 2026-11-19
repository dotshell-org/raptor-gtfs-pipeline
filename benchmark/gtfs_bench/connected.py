"""Step 8: from France side by side ("juxtaposée") to France in one piece ("connexe").

    python -m gtfs_bench.connected                 # build, convert, time and audit both variants
    python -m gtfs_bench.connected --skip-build    # audit and time what is already converted

The regional France tier (steps 3–7) holds every urban, interurban and TER network, linked
only by walking transfers. Two variants are built next to it, each changing one thing:

- **france-patterns**: the same feeds, with every route split into one route per stop
  sequence (merge._split_patterns). The pipeline keeps one stop sequence per route and
  direction and drops the trips that skip one of its stops; split, it keeps them all.
- **france-connexe**: france-patterns plus the long-distance layer of the catalogue (TGV
  INOUI, OUIGO, Intercités, Eurostar, Trenitalia, Renfe, FlixBus, BlaBlaCar Bus, ferries),
  with wider links around the stations of national networks (transfers.StationParams).
- **france-complete** (step 10): france-connexe plus the school layer of the catalogue, the
  feeds that carry only school transport.

Each variant goes through the same chain as any tier: merge, pipeline, engine harness (at
the engine's default 5 rounds, and at 8 for long trips), heap ceilings, plus the step's
two checks: connected components (connectivity.audit) and Paris → every préfecture
(connectivity.reachability). The regional France is measured again at 8 rounds and audited,
not rebuilt. Every converted variant also gets its school lines (gtfs_bench.school) in
school_routes.json next to its .bin files, checked against the engine's own route names,
and the harness times the same trips with and without them. Everything lands in results/
(see RESULTS.md, "France connexe"); running some variants only replaces their own rows.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from . import school as school_lines
from .catalog import read_catalog
from .connectivity import audit, reachability
from .convert import DATA_DIR, MERGED_DIR, RAPTOR_DIR, RESULTS_DIR, convert_tier, write_profile
from .download import download_all, read_manifest
from .engine import run_harness, tier_dir
from .merge import MergeParams, Tier, merge_tier
from .normalize import Window, normalize_all
from .transfers import StationParams, TransferParams


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    layers: tuple[str, ...]
    split_patterns: bool
    stations: StationParams | None

    @property
    def zip_path(self) -> Path:
        if self.key == "france":
            return MERGED_DIR / "france" / "france.zip"
        return MERGED_DIR / "variants" / "france" / f"{self.key}.zip"

    @property
    def data_dir(self) -> Path:
        return tier_dir(self.key)


VARIANTS = (
    Variant("france", "France juxtaposée", ("regional",), False, None),
    Variant("france-patterns", "+ one route per stop sequence", ("regional",), True, None),
    Variant("france-connexe", "France connexe", ("regional", "longue_distance"), True,
            StationParams()),
    Variant("france-complete", "France complète", ("regional", "longue_distance", "scolaire"), True,
            StationParams()),
)
ENGINE_DIR = RESULTS_DIR / "engine" / "variants"
LONG_ROUNDS = 8
HEAP_CHECKS = ("384m", "512m", "1g")


def rows_for(variant: Variant, catalog: list[dict] | None = None) -> list[dict]:
    return [r for r in (catalog or read_catalog()) if r["include"] and r["layer"] in variant.layers]


def prepare(rows: list[dict], window: Window, progress=print) -> list[dict]:
    """Download what is missing and normalize (both cached): returns the rows ready to merge."""
    manifest = read_manifest()
    missing = [r for r in rows if r["feed_id"] not in manifest or not manifest[r["feed_id"]].ok]
    if missing:
        download_all(missing, progress=lambda line: None)
        manifest = read_manifest()
    _, errors = normalize_all(rows, window, {k: m.sha256 for k, m in manifest.items()}, progress=lambda line: None)
    for feed_id, error in errors.items():
        progress(f"  normalization FAILED {feed_id}: {error[:200]}")
    return [r for r in rows if r["feed_id"] not in errors and manifest.get(r["feed_id"]) and manifest[r["feed_id"]].ok]


def build(variant: Variant, reference: dt.date, java: str | None = None, pipeline_xmx: str = "12g",
          transfers: TransferParams = TransferParams(), progress=print) -> dict:
    """Merge and convert one variant. Returns the merge report and the conversion, as dicts."""
    rows = prepare(rows_for(variant), Window.week_of(reference), progress)
    tier = Tier(variant.key, "france", variant.label, tuple(rows), area_code="mainland")
    params = MergeParams(reference_date=reference, transfers=transfers, split_patterns=variant.split_patterns,
                         stations=variant.stations)
    report = merge_tier(tier, params, out_dir=MERGED_DIR / "variants", progress=progress)
    profile = write_profile(reference, DATA_DIR / "profiles" / "bench.yaml")
    conversion = convert_tier(variant.zip_path, RAPTOR_DIR / variant.key, profile, pipeline_xmx, java)
    conversion.tier = variant.key
    progress(f"{variant.key}: pipeline {conversion.status} in {conversion.seconds} s, peak {conversion.peak_memory_mb} MB, "
             f"{conversion.trips} of {conversion.trips_found} trips kept")
    # The log's path is this machine's: it stays out of results/.
    return {"merge": asdict(report), "conversion": {k: v for k, v in asdict(conversion).items() if k != "log"}}


def tag_school(variant: Variant, reference: dt.date, rows: list[dict] | None = None, progress=print) -> dict:
    """The variant's school lines: school_routes.json for the engine, and for the variant with
    the school layer, the list to review (results/school_routes.csv, school_feeds.csv)."""
    lines = school_lines.school_routes(rows if rows is not None else rows_for(variant), reference)
    route_ids, names = school_lines.engine_route_ids(variant.zip_path, set(lines.loc[lines["rule"].notna(), "route_id"]))
    school_lines.write_engine_file(variant.data_dir, route_ids, lines, reference)
    if "scolaire" in variant.layers:
        school_lines.write_review(lines, RESULTS_DIR / "school_routes.csv")
        school_lines.summary(lines).to_csv(RESULTS_DIR / "school_feeds.csv", index=False)
    school = lines[lines["rule"].notna()]
    progress(f"{variant.key}: {len(school)} school lines, {int(school['trips_on_day'].sum())} of "
             f"{int(lines['trips_on_day'].sum())} trips on {reference}, {len(route_ids)} engine routes")
    return {"names": names, "lines": len(school), "route_ids": len(route_ids)}


def check_school_ids(server, names: list[tuple[int, str]]) -> int:
    """Engine routes whose name differs from the merged routes.txt row their number points at:
    a non-zero count means the numbering assumption broke, and the switch would hide the wrong lines."""
    engine = {route_id: name for route_id, name in server.request({"op": "routes"})["routes"]}
    return sum(1 for route_id, name in names if route_id in engine and engine[route_id] != name)


def time_school(variant: Variant, java: str | None = None, progress=print) -> list[dict]:
    """The same trips with and without the school lines (harness --mode school)."""
    report = run_harness(variant.key, "2g", "school", out=ENGINE_DIR / f"{variant.key}-school.json", java=java,
                         data_dir=variant.data_dir)
    extras = report.get("extras") or {}
    rows = []
    for q in report.get("querySets", []):
        name, _, lines = q["name"].partition(":")
        rows.append({"network": variant.key, "query_set": name, "lines": lines, "direction": q["direction"],
                     "queries": q["queries"], "found": q["found"],
                     **{f"latency_{k}_ms": round(v, 3) for k, v in q["latencyMs"].items()},
                     "median_duration_min": q.get("medianDurationMin"),
                     "school_route_ids": extras.get("schoolRouteIds"), "school_trips": extras.get("schoolTrips")})
    progress(f"{variant.key} school switch: {report['status']}")
    return rows


def time_engine(variant: Variant, java: str | None = None, progress=print) -> dict:
    """The harness at 5 and 8 rounds, then the heap checks. Returns the reports by run."""
    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
    runs = {}
    for rounds in (5, LONG_ROUNDS):
        if variant.key == "france" and rounds == 5:  # measured in step 6, kept as is
            runs[rounds] = json.loads((RESULTS_DIR / "engine" / "france.json").read_text(encoding="utf-8"))
            continue
        out = ENGINE_DIR / f"{variant.key}-{rounds}rounds.json"
        runs[rounds] = run_harness(variant.key, out=out, java=java, extra=("--max-rounds", str(rounds)),
                                   data_dir=variant.data_dir)
        progress(f"{variant.key} at {rounds} rounds: {runs[rounds]['status']}")
    heap = {}
    for xmx in HEAP_CHECKS:
        report = run_harness(variant.key, xmx, "heap", out=ENGINE_DIR / "heap" / f"{variant.key}-{xmx}.json", java=java,
                             data_dir=variant.data_dir)
        heap[xmx] = report["status"] if report["status"] == "ok" else f"{report['status']} during {report.get('failedDuring')}"
    progress(f"{variant.key} heap checks: {heap}")
    return {"runs": runs, "heap": heap}


def _latency(report: dict, name: str, direction: str) -> dict:
    q = next((q for q in report.get("querySets", []) if q["name"] == name and q["direction"] == direction), None)
    return q["latencyMs"] if q else {}


def summarize(variant: Variant, built: dict | None, engine: dict, graph, reach: pd.DataFrame,
              school: dict | None = None) -> dict:
    five, eight = engine["runs"][5], engine["runs"][LONG_ROUNDS]
    network = five.get("network") or {}
    pipeline = (built or {}).get("conversion") or _pipeline_row(variant.key)
    merge = (built or {}).get("merge") or _merge_report(variant)
    row = {
        "network": variant.key, "label": variant.label, "feeds": len(merge.get("feeds", [])),
        "routes_from_split": merge.get("routes_from_split", 0), "transfers_stations": merge.get("transfers_stations", 0),
        "merge_seconds": merge.get("seconds"),
        "pipeline_status": pipeline.get("status"), "pipeline_seconds": pipeline.get("seconds"),
        "pipeline_peak_mb": pipeline.get("peak_memory_mb"),
        "trips_found": pipeline.get("trips_found"), "trips_kept": pipeline.get("trips"),
        "trips_kept_share": pipeline.get("trips_kept_share"),
        "stops": network.get("stops"), "routes": network.get("routes"), "trips": network.get("trips"),
        "stop_times": network.get("stopTimes"), "transfers": network.get("transfers"),
        "bins_mb": round(sum((five.get("files") or {}).values()) / 1024**2, 1) if five.get("files") else None,
        "cold_build_ms": round((five.get("load") or {}).get("coldBuildMs", 0)),
        "retained_heap_mb": round((five.get("heap") or {}).get("retainedMb", 0)),
        "peak_heap_mb": round((five.get("heap") or {}).get("peakMb", 0)),
        **{f"fits_{xmx}": status for xmx, status in engine["heap"].items()},
        "giant_component_share": graph.giant_weak_share, "giant_strong_share": graph.giant_strong_share,
        "islands_10_plus": graph.islands_10_plus,
        "prefectures_reached": int(reach["found"].sum()), "prefectures": len(reach),
        "prefecture_median_min": reach.loc[reach["found"], "duration_min"].median(),
        "school_lines": (school or {}).get("lines"), "school_route_ids": (school or {}).get("route_ids"),
    }
    for rounds, report in ((5, five), (LONG_ROUNDS, eight)):
        for direction in ("forward", "arrive_by"):
            latency = _latency(report, "random", direction)
            for p in ("p50", "p95", "p99"):
                row[f"random_{direction}_{p}_ms_{rounds}r"] = round(latency.get(p, float("nan")), 2)
        long_trips = [s for s in report.get("scenarios", []) if s["kind"] == "long-distance"]
        row[f"long_distance_found_{rounds}r"] = f"{sum(s['found'] for s in long_trips)}/{len(long_trips)}"
    return row


def _pipeline_row(key: str) -> dict:
    frame = pd.read_csv(RESULTS_DIR / "pipeline.csv")
    return frame[frame["tier"] == key].iloc[0].to_dict()


def _merge_report(variant: Variant) -> dict:
    path = variant.zip_path.with_name(f"{variant.key}.report.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _replace(path: Path, rows: list[dict], networks: set[str]) -> None:
    """Write `rows` in place of the earlier rows of `networks`, keeping the other networks' rows."""
    kept = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            kept = [r for r in csv.DictReader(handle) if r.get("network") not in networks]
    _write(path, kept + rows)


def run(reference: dt.date, keys: list[str] | None = None, skip_build: bool = False, java: str | None = None,
        progress=print) -> pd.DataFrame:
    from .explorer.backend import EngineServer

    summaries, islands, reaches, scenarios, switches = [], [], [], [], []
    done: set[str] = set()
    for variant in VARIANTS:
        if keys and variant.key not in keys:
            continue
        built = None
        if variant.key != "france" and not skip_build:
            built = build(variant, reference, java, progress=progress)
            (ENGINE_DIR / "builds").mkdir(parents=True, exist_ok=True)
            (ENGINE_DIR / "builds" / f"{variant.key}.json").write_text(json.dumps(built, ensure_ascii=False, indent=1, default=str),
                                                                     encoding="utf-8")
        elif variant.key != "france":
            path = ENGINE_DIR / "builds" / f"{variant.key}.json"
            built = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        school = tag_school(variant, reference, progress=progress)
        graph, _ = audit(variant.zip_path, reference, variant.key)
        progress(f"{variant.key}: {graph.giant_weak_share:.2%} of {graph.active_stops} stops in one piece, "
                 f"{graph.islands_10_plus} islands of 10+ stops")
        engine = time_engine(variant, java, progress)
        server = EngineServer(variant.data_dir, java, "2g")
        try:
            wrong = check_school_ids(server, school["names"])
            if wrong:
                raise RuntimeError(f"{variant.key}: {wrong} school route numbers point at another line in the engine")
            reach = reachability(server, variant.key, progress=progress)
        finally:
            server.close()
        switches += time_school(variant, java, progress)
        done.add(variant.key)
        summaries.append(summarize(variant, built, engine, graph, reach, school))
        islands += graph.islands
        reaches.append(reach)
        for rounds, report in engine["runs"].items():
            for s in report.get("scenarios", []):
                scenarios.append({"network": variant.key, "max_rounds": rounds,
                                  **{k: (", ".join(v) if isinstance(v, list) else v) for k, v in s.items()}})
        _replace(RESULTS_DIR / "connected_france.csv", summaries, done)
        _replace(RESULTS_DIR / "connectivity_islands.csv", islands, done)
        _replace(RESULTS_DIR / "reachability_prefectures.csv", pd.concat(reaches).to_dict("records"), done)
        _replace(RESULTS_DIR / "connected_scenarios.csv", scenarios, done)
        _replace(RESULTS_DIR / "school_switch.csv", switches, done)
    return pd.DataFrame(summaries)


def school_only(reference: dt.date, keys: list[str] | None = None, java: str | None = None, progress=print) -> list[dict]:
    """School lines of variants already converted: school_routes.json, the check against the
    engine, and the with/without timing. Nothing else is measured again."""
    from .explorer.backend import EngineServer

    switches, done = [], set()
    for variant in VARIANTS:
        if (keys and variant.key not in keys) or not (variant.data_dir / "routes.bin").exists():
            continue
        school = tag_school(variant, reference, progress=progress)
        server = EngineServer(variant.data_dir, java, "1g")
        try:
            wrong = check_school_ids(server, school["names"])
        finally:
            server.close()
        if wrong:
            raise RuntimeError(f"{variant.key}: {wrong} school route numbers point at another line in the engine")
        switches += time_school(variant, java, progress)
        done.add(variant.key)
        _replace(RESULTS_DIR / "school_switch.csv", switches, done)
    return switches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.connected", description=__doc__.splitlines()[0])
    parser.add_argument("--variants", help="comma-separated: " + ", ".join(v.key for v in VARIANTS))
    parser.add_argument("--skip-build", action="store_true", help="reuse the merged and converted variants")
    parser.add_argument("--school-only", action="store_true",
                        help="only tag the school lines of converted variants and time the switch")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    args = parser.parse_args(argv)
    reference = dt.date.fromisoformat(json.loads((RESULTS_DIR / "reference_day.json").read_text(encoding="utf-8"))["reference_date"])
    if args.school_only:
        rows = school_only(reference, args.variants.split(",") if args.variants else None, args.java)
        print(pd.DataFrame(rows).to_string())
        return 0
    table = run(reference, args.variants.split(",") if args.variants else None, args.skip_build, args.java)
    print(table.T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
