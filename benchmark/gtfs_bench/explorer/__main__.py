"""python -m gtfs_bench.console (or gtfs_bench.explorer) [--tier france-live] [--java …] [--xmx 2g]

The benchmark's console: itinerary, catalogue, networks, actions (every step of the
notebook), settings, results and the guide, in one terminal app.
"""

import argparse
import sys

from ..catalog import BENCHMARK_DIR
from ..convert import RAPTOR_DIR
from ..engine import tier_dir
from ..horizon import Plan
from ..settings import load as load_settings
from .app import NETWORK_NAMES, Explorer, reference_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.explorer",
                                     description="The benchmark console: itinerary, catalogue, networks, actions, settings, results, guide.")
    parser.add_argument("--tier", default=None,
                        help="france-live (the default once gtfs_bench.refresh has built it: any date of its window), "
                             "france, france-connexe, france-complete, region:84, metropole:lyon… (a converted tier)")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    # France loads in 384m; each extra RAPTOR round then costs ~9.4 MB of search state, so the
    # explorer's top limit (99 changes = 100 rounds) needs ~1.2 GB on France.
    parser.add_argument("--xmx", default=None, help="engine heap (default: the settings, 2g; 99 changes need ~1.2g)")
    args = parser.parse_args(argv)

    settings = load_settings()
    tier = args.tier or settings.explorer.default_network or (
        "france-live" if (RAPTOR_DIR / "france-live" / "horizon.json").exists() else "france")
    live = RAPTOR_DIR / tier
    plan = Plan.read(live / "horizon.json") if (live / "horizon.json").exists() else None
    data = live if plan else tier_dir(tier)
    if not plan and not (data / "routes.bin").exists():
        print(f"{data} has no routes.bin: run the notebook (or gtfs_bench.convert) for {tier} first.", file=sys.stderr)
        return 1
    app = Explorer(data, NETWORK_NAMES.get(tier, tier), args.java, args.xmx or settings.explorer.xmx,
                   cache_dir=BENCHMARK_DIR / "data" / "tmp" / "explorer",
                   reference_day=reference_day(BENCHMARK_DIR / "results"), plan=plan)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
