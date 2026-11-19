"""python -m gtfs_bench.console: the benchmark's terminal console (see gtfs_bench.explorer)."""

import sys

from .explorer.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
