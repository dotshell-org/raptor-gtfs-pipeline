"""python -m gtfs_bench.explorer [--tier france-live] [--java …] [--xmx 2g]"""

import argparse
import sys

from ..catalog import BENCHMARK_DIR
from ..convert import RAPTOR_DIR
from ..engine import tier_dir
from ..horizon import Plan
from .app import Explorer, reference_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.explorer",
                                     description="Pick two stops, get the itinerary from raptor-kmp.")
    parser.add_argument("--tier", default=None,
                        help="france-live (the default once gtfs_bench.refresh has built it: any date of its window), "
                             "france, france-connexe, france-complete, region:84, metropole:lyon… (a converted tier)")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    # France loads in 384m; each extra RAPTOR round then costs ~9.4 MB of search state, so the
    # explorer's top limit (99 changes = 100 rounds) needs ~1.2 GB on France.
    parser.add_argument("--xmx", default="2g", help="engine heap (France loads in 384m; 99 changes need ~1.2g)")
    args = parser.parse_args(argv)

    tier = args.tier or ("france-live" if (RAPTOR_DIR / "france-live" / "horizon.json").exists() else "france")
    live = RAPTOR_DIR / tier
    plan = Plan.read(live / "horizon.json") if (live / "horizon.json").exists() else None
    data = live if plan else tier_dir(tier)
    if not plan and not (data / "routes.bin").exists():
        print(f"{data} has no routes.bin: run the notebook (or gtfs_bench.convert) for {tier} first.", file=sys.stderr)
        return 1
    names = {"france": "France métropolitaine", "france-connexe": "France connexe (TGV, Intercités, cars, ferries)",
             "france-patterns": "France, une ligne par desserte",
             "france-complete": "France complète (connexe + transport scolaire)",
             "france-live": "France complète, données à jour"}
    app = Explorer(data, names.get(tier, tier), args.java, args.xmx,
                   cache_dir=BENCHMARK_DIR / "data" / "tmp" / "explorer",
                   reference_day=reference_day(BENCHMARK_DIR / "results"), plan=plan)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
