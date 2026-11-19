"""What raptor-kmp's same-name links cost: France merged with the producers' stop names.

raptor-kmp links every pair of stops sharing an exact name with a 120 s transfer
(Network.implicitTransferData). The merge renames homonyms by place so that those links
stay inside one place. This variant skips the renaming, converts and times the result
exactly like the real France tier, and lays the two side by side in
results/engine_same_name_links.csv.

    python -m gtfs_bench.variants
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys

from .catalog import read_catalog
from .convert import DATA_DIR, MERGED_DIR, RAPTOR_DIR, RESULTS_DIR, convert_tier, write_profile
from .engine import run_harness, tier_dir
from .merge import MergeParams, merge_tier, tiers_from_catalog

VARIANT = "france-raw-names"


def same_name_variant(reference: dt.date, java: str | None = None, progress=print) -> list[dict]:
    rows = [r for r in read_catalog() if r["include"] and r["layer"] == "regional"]
    tier = tiers_from_catalog(rows)["france"]
    merge_tier(tier, MergeParams(reference_date=reference, rename_homonyms=False), out_dir=MERGED_DIR / "variants",
               progress=progress)
    profile = write_profile(reference, DATA_DIR / "profiles" / "bench.yaml")
    conversion = convert_tier(MERGED_DIR / "variants" / "france" / "france.zip", RAPTOR_DIR / VARIANT, profile, java=java)
    progress(f"{VARIANT}: pipeline {conversion.status} in {conversion.seconds} s, peak {conversion.peak_memory_mb} MB")
    out = RESULTS_DIR / "engine" / "variants"
    raw = run_harness("france", out=out / f"{VARIANT}.json", java=java, data_dir=RAPTOR_DIR / VARIANT / "bench")
    sweep = {xmx: run_harness("france", xmx, "heap", out=out / f"{VARIANT}-{xmx}.json", java=java,
                              data_dir=RAPTOR_DIR / VARIANT / "bench")["status"] for xmx in ("384m", "512m", "1g")}
    renamed = json.loads((RESULTS_DIR / "engine" / "france.json").read_text(encoding="utf-8"))

    def facts(report: dict, label: str) -> list[dict]:
        out_rows = []
        for q in report.get("querySets", []):
            out_rows.append({
                "variant": label, "status": report["status"],
                "implicit_transfer_pairs": report["network"]["implicitTransferPairs"],
                "largest_name_group": report["network"]["largestNameGroup"],
                "cold_build_ms": round(report["load"]["coldBuildMs"], 1),
                "retained_heap_mb": round(report["heap"]["retainedMb"], 1),
                "peak_heap_mb": round(report["heap"]["peakMb"], 1),
                "query_set": q["name"], "direction": q["direction"], "queries": q["queries"], "found": q["found"],
                "latency_p50_ms": round(q["latencyMs"]["p50"], 3), "latency_p95_ms": round(q["latencyMs"]["p95"], 3),
                "latency_p99_ms": round(q["latencyMs"]["p99"], 3),
                "median_duration_min": q.get("medianDurationMin"),
            })
        return out_rows

    table = facts(renamed, "renamed (benchmark)") + facts(raw, "producers' names")
    for row in table:
        row["fits_384m"] = "" if row["variant"].startswith("renamed") else sweep["384m"]
        row["fits_512m"] = "" if row["variant"].startswith("renamed") else sweep["512m"]
    path = RESULTS_DIR / "engine_same_name_links.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    progress(f"{VARIANT}: engine {raw['status']}, heap sweep {sweep} -> {path}")
    return table


def main() -> int:
    reference = dt.date.fromisoformat(json.loads((RESULTS_DIR / "reference_day.json").read_text(encoding="utf-8"))["reference_date"])
    same_name_variant(reference)
    return 0


if __name__ == "__main__":
    sys.exit(main())
