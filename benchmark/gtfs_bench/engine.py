"""Time raptor-kmp on every converted tier, and find the smallest heap each one fits in.

    python -m gtfs_bench.engine                     # full run on every tier, then the heap sweep
    python -m gtfs_bench.engine --tiers france --no-sweep

The harness is the :benchmark-engine module (benchmark/engine), built with
`./gradlew :benchmark-engine:installDist`. Each run is its own JVM, so every load is a cold
one and a tier that does not fit cannot disturb the next. Reports land in
results/engine/<tier>.json; the flat tables in results/engine.csv (one row per tier and
query set), results/engine_scenarios.csv and results/engine_heap.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

from .catalog import BENCHMARK_DIR
from .convert import RAPTOR_DIR, RESULTS_DIR, java_executable, merged_tiers

ENGINE_DIR = BENCHMARK_DIR / "engine"
ENGINE_INSTALL = ENGINE_DIR / "build" / "install" / "benchmark-engine"
MAIN_CLASS = "eu.dotshell.raptor.bench.MainKt"
#: Heap ceilings for the sweep. Android gives an app 192–256 MB on many phones
#: (ActivityManager.getMemoryClass), and 512 MB or more with android:largeHeap on recent ones.
SWEEP_XMX = ("256m", "384m", "512m", "1g", "2g", "4g")
SWEEP_TIERS = ("metropole:lyon", "region:84", "region:11", "france")


def tier_dir(key: str) -> Path:
    stem = "france" if key == "france" else key.replace(":", "-")
    return RAPTOR_DIR / stem / "bench"


def run_harness(key: str, xmx: str = "12g", mode: str = "full", out: Path | None = None, java: str | None = None,
                extra: tuple[str, ...] = (), timeout_s: int = 3600, data_dir: Path | None = None,
                install: Path = ENGINE_INSTALL) -> dict:
    """One JVM, one tier. Returns the harness's report plus the process's peak working set.

    `install` is the harness's installDist folder: another one (a copy built against another
    raptor-kmp, see engines.py) times that engine instead."""
    if not (install / "lib").exists():
        raise FileNotFoundError(f"{install} is missing: run ./gradlew :benchmark-engine:installDist")
    out = out or RESULTS_DIR / "engine" / f"{key.replace(':', '-')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    command = [java_executable(java), f"-Xmx{xmx}", "-cp", str(install / "lib" / "*"), MAIN_CLASS,
               "--data", str(data_dir or tier_dir(key)), "--tier", key, "--out", str(out), "--mode", mode,
               "--areas", str(ENGINE_DIR / "areas.csv"), "--scenarios", str(ENGINE_DIR / "scenarios.csv"), *extra]
    started = time.perf_counter()
    peak = 0.0
    process = psutil.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while process.poll() is None:
        try:
            info = process.memory_info()
            peak = max(peak, float(getattr(info, "peak_wset", info.rss)))
        except psutil.Error:
            pass
        if time.perf_counter() - started > timeout_s:
            process.kill()
            break
        time.sleep(0.2)
    output = process.stdout.read() if process.stdout else ""
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {
        "tier": key, "status": "failed", "error": output.strip()[-500:] or f"exit {process.returncode}"}
    report["process"] = {"xmx": xmx, "exit_code": process.returncode, "seconds": round(time.perf_counter() - started, 1),
                         "peak_working_set_mb": round(peak / 1024**2)}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def flatten(report: dict) -> list[dict]:
    """One row per query set, with the tier's load and size columns repeated."""
    base = {
        "tier": report["tier"], "status": report["status"],
        "stops": (report.get("network") or {}).get("stops"), "routes": (report.get("network") or {}).get("routes"),
        "trips": (report.get("network") or {}).get("trips"), "stop_times": (report.get("network") or {}).get("stopTimes"),
        "transfers": (report.get("network") or {}).get("transfers"),
        "implicit_transfer_pairs": (report.get("network") or {}).get("implicitTransferPairs"),
        "bins_mb": round(sum((report.get("files") or {}).values()) / 1024**2, 2) if report.get("files") else None,
        "cold_build_ms": (report.get("load") or {}).get("coldBuildMs"),
        "warm_build_median_ms": (report.get("load") or {}).get("warmBuildMedianMs"),
        "retained_heap_mb": (report.get("heap") or {}).get("retainedMb"),
        "peak_heap_mb": (report.get("heap") or {}).get("peakMb"),
        "peak_working_set_mb": report.get("process", {}).get("peak_working_set_mb"),
    }
    rows = []
    for q in report.get("querySets", []):
        latency = q["latencyMs"]
        rows.append({**base, "query_set": q["name"], "direction": q["direction"], "queries": q["queries"],
                     "found": q["found"], **{f"latency_{k}_ms": round(v, 3) for k, v in latency.items()},
                     "median_duration_min": q.get("medianDurationMin"), "median_transit_legs": q.get("medianTransitLegs"),
                     "note": q.get("note") or ""})
    return rows or [base]


def run_all(tiers: list[str] | None = None, xmx: str = "12g", java: str | None = None, progress=print) -> list[dict]:
    reports = []
    for key, _ in merged_tiers():
        if tiers and key not in tiers:
            continue
        if not (tier_dir(key) / "routes.bin").exists():
            progress(f"{key}: not converted, skipped")
            continue
        report = run_harness(key, xmx, "full", java=java)
        reports.append(report)
        forward = next((q for q in report.get("querySets", []) if q["name"] == "random" and q["direction"] == "forward"), None)
        progress(f"{key}: {report['status']}" + (
            f", build {report['load']['coldBuildMs']:.0f} ms, heap {report['heap']['retainedMb']:.0f} MB, "
            f"random forward p50 {forward['latencyMs']['p50']:.2f} ms" if report["status"] == "ok" and forward else
            f" — {report.get('error', '')}"))
        write_tables(reports)
    return reports


def heap_sweep(tiers=SWEEP_TIERS, ceilings=SWEEP_XMX, java: str | None = None, progress=print) -> list[dict]:
    rows = []
    for key in tiers:
        for xmx in ceilings:
            report = run_harness(key, xmx, "heap", out=RESULTS_DIR / "engine" / "heap" / f"{key.replace(':', '-')}-{xmx}.json", java=java)
            forward = next((q for q in report.get("querySets", [])), None)
            rows.append({
                "tier": key, "xmx": xmx, "status": report["status"], "failed_during": report.get("failedDuring") or "",
                "cold_build_ms": (report.get("load") or {}).get("coldBuildMs"),
                "retained_heap_mb": (report.get("heap") or {}).get("retainedMb"),
                "peak_heap_mb": (report.get("heap") or {}).get("peakMb"),
                "peak_working_set_mb": report["process"]["peak_working_set_mb"],
                "random_forward_p50_ms": forward["latencyMs"]["p50"] if forward else None,
                "random_forward_p95_ms": forward["latencyMs"]["p95"] if forward else None,
            })
            progress(f"{key} at -Xmx{xmx}: {report['status']}" + (f" during {report.get('failedDuring')}" if report["status"] != "ok" else ""))
            _write_csv(RESULTS_DIR / "engine_heap.csv", rows)
    return rows


ADDRESS_TIERS = ("metropole:lyon", "france-connexe")


def address_costs(tiers=ADDRESS_TIERS, xmx: str = "2g", java: str | None = None, progress=print) -> list[dict]:
    """What searching from an address costs, against searching from stops (harness --mode points).

    One row per tier, query set and way of asking (nearest stop, stops within 500 m, address),
    in results/address_queries.csv; the reports in results/engine/address/. address_grid_mb is
    the heap the first address search adds (raptor-kmp's spatial grid of the stops).
    """
    rows = []
    for key in tiers:
        report = run_harness(key, xmx, "points", out=RESULTS_DIR / "engine" / "address" / f"{key.replace(':', '-')}.json",
                             java=java)
        grid = (report.get("extras") or {}).get("addressGridMb")
        for row in flatten(report):
            name, _, way = row.get("query_set", "").partition(":")
            rows.append({"tier": key, "status": row["status"], "query_set": name, "asked_as": way,
                         "direction": row.get("direction"), "queries": row.get("queries"), "found": row.get("found"),
                         **{k: v for k, v in row.items() if k.startswith("latency_")},
                         "median_duration_min": row.get("median_duration_min"), "address_grid_mb": grid})
        progress(f"{key}: {report['status']}" + (f", grid {grid:.1f} MB" if grid is not None else ""))
        _write_csv(RESULTS_DIR / "address_queries.csv", rows)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_tables(reports: list[dict]) -> None:
    _write_csv(RESULTS_DIR / "engine.csv", [row for r in reports for row in flatten(r)])
    _write_csv(RESULTS_DIR / "engine_scenarios.csv", [
        {"tier": r["tier"], **{k: (", ".join(v) if isinstance(v, list) else v) for k, v in s.items()}}
        for r in reports for s in r.get("scenarios", []) if s.get("note") != "not covered by this tier"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.engine", description=__doc__.splitlines()[0])
    parser.add_argument("--tiers", help="comma-separated tier keys (default: every converted tier)")
    from .settings import load
    parser.add_argument("--xmx", default=load().engine.benchmark_xmx, help="heap ceiling of the full runs")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    parser.add_argument("--no-sweep", action="store_true", help="skip the heap-ceiling sweep")
    parser.add_argument("--addresses", action="store_true",
                        help="only time address searches against stop searches (--tiers, default Lyon and France connexe)")
    args = parser.parse_args(argv)
    if args.addresses:
        rows = address_costs(tuple(args.tiers.split(",")) if args.tiers else ADDRESS_TIERS,
                             args.xmx if args.xmx != "12g" else "2g", args.java)
        return 0 if rows and all(r["status"] == "ok" for r in rows) else 1
    reports = run_all(args.tiers.split(",") if args.tiers else None, args.xmx, args.java)
    if not args.no_sweep:
        heap_sweep(java=args.java)
    return 0 if all(r["status"] == "ok" for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
