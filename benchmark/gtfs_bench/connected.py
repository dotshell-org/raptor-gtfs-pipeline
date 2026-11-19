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

Each variant goes through the same chain as any tier: merge, pipeline, engine harness (at
the engine's default 5 rounds, and at 8 for long trips), heap ceilings, plus the step's
two checks: connected components (connectivity.audit) and Paris → every préfecture
(connectivity.reachability). The regional France is measured again at 8 rounds and audited,
not rebuilt. Everything lands in results/ (see RESULTS.md, "France connexe").
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


def summarize(variant: Variant, built: dict | None, engine: dict, graph, reach: pd.DataFrame) -> dict:
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


def run(reference: dt.date, keys: list[str] | None = None, skip_build: bool = False, java: str | None = None,
        progress=print) -> pd.DataFrame:
    from .explorer.backend import EngineServer

    summaries, islands, reaches, scenarios = [], [], [], []
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
        graph, _ = audit(variant.zip_path, reference, variant.key)
        progress(f"{variant.key}: {graph.giant_weak_share:.2%} of {graph.active_stops} stops in one piece, "
                 f"{graph.islands_10_plus} islands of 10+ stops")
        engine = time_engine(variant, java, progress)
        server = EngineServer(variant.data_dir, java, "2g")
        try:
            reach = reachability(server, variant.key, progress=progress)
        finally:
            server.close()
        summaries.append(summarize(variant, built, engine, graph, reach))
        islands += graph.islands
        reaches.append(reach)
        for rounds, report in engine["runs"].items():
            for s in report.get("scenarios", []):
                scenarios.append({"network": variant.key, "max_rounds": rounds,
                                  **{k: (", ".join(v) if isinstance(v, list) else v) for k, v in s.items()}})
        _write(RESULTS_DIR / "connected_france.csv", summaries)
        _write(RESULTS_DIR / "connectivity_islands.csv", islands)
        pd.concat(reaches).to_csv(RESULTS_DIR / "reachability_prefectures.csv", index=False)
        _write(RESULTS_DIR / "connected_scenarios.csv", scenarios)
    return pd.DataFrame(summaries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.connected", description=__doc__.splitlines()[0])
    parser.add_argument("--variants", help="comma-separated: " + ", ".join(v.key for v in VARIANTS))
    parser.add_argument("--skip-build", action="store_true", help="reuse the merged and converted variants")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    args = parser.parse_args(argv)
    reference = dt.date.fromisoformat(json.loads((RESULTS_DIR / "reference_day.json").read_text(encoding="utf-8"))["reference_date"])
    table = run(reference, args.variants.split(",") if args.variants else None, args.skip_build, args.java)
    print(table.T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
