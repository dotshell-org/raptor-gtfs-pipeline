"""Build the métropoles and regions as live networks, without measuring anything.

    python -m gtfs_bench.tiers                                    # the 22 métropoles and 13 regions
    python -m gtfs_bench.tiers --tiers metropole:lyon,region:84

The operational part of the notebook only: the feeds (downloaded if missing), normalized over
the live window, merged per tier and converted with the same day types as france-live
(gtfs_bench.horizon: semaine, samedi, dimanche), school lines tagged per period. Every tier
lands in data/raptor/<kind>-<name>/<day type>/, where the console's Networks tab finds it.
No benchmark, nothing written to results/.

The window and day types are france-live's (its horizon.json) when it exists, so the tiers
and the whole of France run the same days; otherwise they are computed here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from . import school as school_lines
from .connected import prepare
from .convert import DATA_DIR, MERGED_DIR, RAPTOR_DIR, convert_tier, write_day_types_profile
from .horizon import Plan, plan as make_plan
from .merge import MergeParams, tiers_from_catalog, merge_tier
from .refresh import LIVE_DIR, live_rows
from .settings import load as load_settings

#: France-live's layers except the long-distance one, which only the whole of France carries.
LAYERS = ("regional", "scolaire")


def current_plan(today: dt.date | None = None) -> Plan:
    path = LIVE_DIR / "horizon.json"
    if path.exists():
        return Plan.read(path)
    settings = load_settings().live
    return make_plan(live_rows(), today or dt.date.today(), settings.max_feed_share, settings.max_lost_share)[0]


def build_tiers(keys: list[str] | None = None, java: str | None = None, progress=print) -> dict[str, str]:
    """Merge and convert every selected tier. Returns tier key -> "ok" or the error."""
    settings = load_settings()
    result = current_plan()
    days = {name: dt.date.fromisoformat(day) for name, day in result.days.items()}
    main = days["semaine"]
    progress(f"day types {result.days}, window {result.start} -> {result.end}")

    rows = [r for r in live_rows() if r["layer"] in LAYERS]
    ready = prepare(rows, result.normalization_window(), progress)
    tiers = [t for key, t in tiers_from_catalog(ready, LAYERS).items()
             if t.kind != "france" and (not keys or key in keys)]
    params = MergeParams(reference_date=main, transfers=settings.merge.transfer_params(), split_patterns=True,
                         name_radius_m=settings.merge.name_radius_m, memory_limit=settings.merge.duckdb_memory)
    outcome = {}
    for i, tier in enumerate(tiers, 1):
        started = time.perf_counter()
        try:
            report = merge_tier(tier, params, progress=lambda line: None)
            zip_path = MERGED_DIR / tier.kind / f"{tier.kind}-{tier.key.split(':', 1)[1]}.zip"
            out_dir = RAPTOR_DIR / zip_path.stem
            profile = write_day_types_profile(days, DATA_DIR / "profiles" / f"{zip_path.stem}.yaml", network=zip_path.stem)
            conversion = convert_tier(zip_path, out_dir, profile, settings.engine.pipeline_xmx, java, period="semaine")
            if conversion.status != "ok":
                raise RuntimeError(f"pipeline {conversion.status}: {conversion.error}")
            lines = school_lines.school_routes(list(tier.rows), main, few_runs=settings.school.few_runs)
            route_ids, _ = school_lines.engine_route_ids(zip_path, set(lines.loc[lines["rule"].notna(), "route_id"]))
            for name in days:
                school_lines.write_engine_file(out_dir / name, route_ids, lines, main)
            (out_dir / "horizon.json").write_text(result.to_json(), encoding="utf-8")
            outcome[tier.key] = "ok"
            progress(f"[{i}/{len(tiers)}] {tier.key} ({tier.name}): {len(tier.rows)} feeds, "
                     f"{report.trips_on_reference_date} trips on {main}, {time.perf_counter() - started:.0f} s")
        except Exception as error:  # one broken tier must not stop the others
            outcome[tier.key] = str(error)
            progress(f"[{i}/{len(tiers)}] {tier.key} FAILED: {error}")
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.tiers", description=__doc__.splitlines()[0])
    parser.add_argument("--tiers", help="comma-separated tier keys (default: every métropole and region)")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    args = parser.parse_args(argv)
    outcome = build_tiers(args.tiers.split(",") if args.tiers else None, args.java)
    ok = sum(v == "ok" for v in outcome.values())
    print(f"{ok}/{len(outcome)} tiers built in {RAPTOR_DIR}")
    return 0 if ok == len(outcome) else 1


if __name__ == "__main__":
    sys.exit(main())
