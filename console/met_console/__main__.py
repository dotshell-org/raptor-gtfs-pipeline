"""python -m met_console [--data <dir>] [--java …] [--xmx 1g]

The france-live console: itinerary, updates, data, settings and the guide, in one terminal app.
"""

import argparse
import sys
from pathlib import Path

from .app import Explorer
from .paths import DEFAULT_DATA_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m met_console",
                                     description="The france-live console: itinerary, updates, data, settings, guide.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_DIR,
                        help="where the installed version, the caches and the settings live (default: console/data)")
    parser.add_argument("--java", help="java executable (default: the settings, $JAVA_HOME, then PATH)")
    parser.add_argument("--xmx", help="engine heap (default: the settings, 1g; 99 changes need ~1.2g)")
    args = parser.parse_args(argv)
    Explorer(args.data.resolve(), args.java, args.xmx).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
