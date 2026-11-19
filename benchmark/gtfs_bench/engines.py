"""Compare raptor-kmp builds on the same networks: same journeys, how much memory, how fast.

    python -m gtfs_bench.engines publish                  # raptor-kmp working copy -> ~/.m2 (its version)
    python -m gtfs_bench.engines install 2.2.0            # harness against Maven Central's 2.2.0
    python -m gtfs_bench.engines install 2.4.0-SNAPSHOT --local
    python -m gtfs_bench.engines compare 2.2.0 2.4.0-SNAPSHOT

Each harness build is kept in data/tmp/engines/<version>/ (a copy of installDist), so
several engines can be timed side by side while build/install keeps the default one for the
explorer. `compare` runs, on every network given, the golden journeys (the exact output of
fixed queries, hashed: they must match), the retained heap and its class histogram, the
full timing run, and the smallest heap each engine fits in; everything lands in
results/engine/memory/ and results/engine_memory.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .catalog import BENCHMARK_DIR
from .convert import DATA_DIR, RAPTOR_DIR, RESULTS_DIR, java_executable
from .engine import ENGINE_INSTALL, run_harness

REPO_DIR = BENCHMARK_DIR.parent
RAPTOR_KMP_DIR = REPO_DIR.parent / "raptor-kmp"
ENGINES_DIR = DATA_DIR / "tmp" / "engines"
MEMORY_DIR = RESULTS_DIR / "engine" / "memory"
DEFAULT_VERSION = "2.2.0"
#: Networks compared, as (name, folder holding stops.bin/routes.bin).
NETWORKS = (("metropole-lyon", RAPTOR_DIR / "metropole-lyon" / "bench"),
            ("france-connexe", RAPTOR_DIR / "france-connexe" / "bench"),
            ("france-complete", RAPTOR_DIR / "france-complete" / "bench"),
            ("france-live-semaine", RAPTOR_DIR / "france-live" / "semaine"))
HEAPS = ("160m", "192m", "224m", "256m", "320m", "384m")
#: AGP 9 refuses the Kotlin Multiplatform plugin unless told to keep the old integration;
#: raptor-kmp's own gradle.properties (not in git) is expected to say so.
AGP_FLAGS = ("-Pandroid.builtInKotlin=false", "-Pandroid.newDsl=false")


def _gradle(cwd: Path, *args: str, java_home: str | None = None) -> None:
    env = dict(os.environ)
    if java_home:
        env["JAVA_HOME"] = java_home
    env.setdefault("ANDROID_HOME", str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"))
    wrapper = cwd / ("gradlew.bat" if os.name == "nt" else "gradlew")
    subprocess.run([str(wrapper), *args, "-q", "--console=plain"], cwd=cwd, env=env, check=True)


def publish(java_home: str | None = None) -> None:
    """The raptor-kmp working copy's JVM artifact, to the local Maven repository."""
    _gradle(RAPTOR_KMP_DIR, "publishJvmPublicationToMavenLocal", *AGP_FLAGS, java_home=java_home)


def install(version: str, local: bool = False, java_home: str | None = None) -> Path:
    """The harness built against raptor-kmp `version`, copied to data/tmp/engines/<version>."""
    args = [":benchmark-engine:installDist", f"-PraptorKmpVersion={version}"] + (["-PraptorKmpLocal"] if local else [])
    _gradle(REPO_DIR, *args, java_home=java_home)
    target = ENGINES_DIR / version
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ENGINE_INSTALL, target)
    if version != DEFAULT_VERSION:  # build/install goes back to the engine the explorer uses
        _gradle(REPO_DIR, ":benchmark-engine:installDist", java_home=java_home)
    return target


def _safe(version: str) -> str:
    return version.replace(".", "_")


def golden(version: str, name: str, data: Path, java: str | None = None) -> dict:
    out = MEMORY_DIR / "golden" / f"{name}-{_safe(version)}.json"
    return run_harness(name, "2g", "golden", out=out, java=java, data_dir=data, install=ENGINES_DIR / version)


def compare_golden(a: dict, b: dict) -> dict[str, str]:
    """Per query set: "same", or how many queries differ and the first one."""
    verdict = {}
    for key, hashes in a.get("goldenQueries", {}).items():
        other = b.get("goldenQueries", {}).get(key)
        if other is None:
            verdict[key] = "missing"
            continue
        diff = [i for i, (x, y) in enumerate(zip(hashes, other)) if x != y]
        verdict[key] = "same" if not diff and len(hashes) == len(other) else f"{len(diff)} differ, first #{diff[0] if diff else '-'}"
    return verdict


def heap_floor(version: str, name: str, data: Path, java: str | None = None) -> dict[str, str]:
    """Load plus 200 queries under each ceiling, smallest first; stops at the first that fits."""
    found = {}
    for xmx in HEAPS:
        report = run_harness(name, xmx, "heap", out=MEMORY_DIR / "heap" / f"{name}-{_safe(version)}-{xmx}.json", java=java,
                             data_dir=data, install=ENGINES_DIR / version)
        found[xmx] = report["status"] if report["status"] == "ok" else f"{report['status']} during {report.get('failedDuring')}"
        if report["status"] == "ok":
            break
    return found


def measure(version: str, name: str, data: Path, java: str | None = None) -> dict:
    """Full timing run, plus the class histogram of the loaded network."""
    histogram = MEMORY_DIR / "histogram" / f"{name}-{_safe(version)}.txt"
    report = run_harness(name, "2g", "full", out=MEMORY_DIR / "full" / f"{name}-{_safe(version)}.json", java=java,
                         data_dir=data, install=ENGINES_DIR / version, extra=("--histogram", str(histogram), "--loads", "3"))
    return report


def _latency(report: dict, name: str, direction: str, p: str) -> float | None:
    q = next((q for q in report.get("querySets", []) if q["name"] == name and q["direction"] == direction), None)
    return round(q["latencyMs"][p], 2) if q else None


def compare(base: str, candidate: str, networks=NETWORKS, java: str | None = None, progress=print) -> list[dict]:
    rows = []
    for name, data in networks:
        if not (data / "routes.bin").exists():
            progress(f"{name}: not converted, skipped")
            continue
        g = {v: golden(v, name, data, java) for v in (base, candidate)}
        verdict = compare_golden(g[base], g[candidate])
        same = all(v == "same" for v in verdict.values())
        progress(f"{name}: golden journeys {'identical' if same else 'DIFFER'} {verdict if not same else ''}")
        for version in (base, candidate):
            full = measure(version, name, data, java)
            floor = heap_floor(version, name, data, java)
            fits = next((x for x, s in floor.items() if s == "ok"), None)
            row = {"network": name, "engine": version, "golden": "same" if same else json.dumps(verdict),
                   "stops": (full.get("network") or {}).get("stops"), "trips": (full.get("network") or {}).get("trips"),
                   "retained_heap_mb": round((full.get("heap") or {}).get("retainedMb", 0), 1),
                   "cold_build_ms": round((full.get("load") or {}).get("coldBuildMs", 0)),
                   "warm_build_median_ms": round((full.get("load") or {}).get("warmBuildMedianMs") or 0),
                   "smallest_heap": fits or "> " + HEAPS[-1],
                   **{f"{s}_{d}_{p}_ms": _latency(full, s, d, p) for s in ("random",) for d in ("forward", "arrive_by")
                      for p in ("p50", "p95", "p99")},
                   **{f"{s}_forward_p50_ms": _latency(full, s, "forward", "p50") for s in ("lyon-local", "paris-local")}}
            rows.append(row)
            progress(f"  {version}: {row['retained_heap_mb']} MB held, fits {row['smallest_heap']}, "
                     f"random p50 {row['random_forward_p50_ms']} / p95 {row['random_forward_p95_ms']} ms")
            _write(RESULTS_DIR / "engine_memory.csv", rows)
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.engines", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("publish")
    p = sub.add_parser("install")
    p.add_argument("version")
    p.add_argument("--local", action="store_true", help="from ~/.m2 (gtfs_bench.engines publish)")
    p = sub.add_parser("compare")
    p.add_argument("base")
    p.add_argument("candidate")
    p.add_argument("--networks", help="comma-separated: " + ", ".join(n for n, _ in NETWORKS))
    parser.add_argument("--java-home", help="JDK for Gradle (default: $JAVA_HOME)")
    args = parser.parse_args(argv)
    if args.command == "publish":
        publish(args.java_home)
    elif args.command == "install":
        print(install(args.version, args.local, args.java_home))
    else:
        wanted = set(args.networks.split(",")) if args.networks else None
        compare(args.base, args.candidate, [n for n in NETWORKS if not wanted or n[0] in wanted])
    return 0


if __name__ == "__main__":
    sys.exit(main())
