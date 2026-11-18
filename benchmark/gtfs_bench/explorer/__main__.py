"""python -m gtfs_bench.explorer [--tier france] [--java …] [--xmx 1g]"""

import argparse
import sys

from ..catalog import BENCHMARK_DIR
from ..engine import tier_dir
from .app import Explorer, reference_day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.explorer",
                                     description="Pick two stops, get the itinerary from raptor-kmp.")
    parser.add_argument("--tier", default="france", help="france, region:84, metropole:lyon… (a converted tier)")
    parser.add_argument("--java", help="java executable (default: $JAVA_HOME, then PATH)")
    parser.add_argument("--xmx", default="1g", help="engine heap (France needs at least 384m)")
    args = parser.parse_args(argv)

    data = tier_dir(args.tier)
    if not (data / "routes.bin").exists():
        print(f"{data} has no routes.bin: run the notebook (or gtfs_bench.convert) for {args.tier} first.", file=sys.stderr)
        return 1
    names = {"france": "France métropolitaine"}
    app = Explorer(data, names.get(args.tier, args.tier), args.java, args.xmx,
                   cache_dir=BENCHMARK_DIR / "data" / "tmp" / "explorer",
                   reference_day=reference_day(BENCHMARK_DIR / "results"))
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
