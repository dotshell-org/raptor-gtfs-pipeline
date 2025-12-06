"""Benchmark tests."""

from pathlib import Path

import pytest

from raptor_pipeline import convert
from raptor_pipeline.gtfs.models import ConvertConfig


@pytest.mark.benchmark
def test_bench_convert_minimal(gtfs_minimal: Path, tmp_path: Path, benchmark: object) -> None:
    """Benchmark conversion of minimal fixture."""

    def do_convert() -> None:
        output = tmp_path / "bench_minimal"
        output.mkdir(exist_ok=True)
        convert(
            str(gtfs_minimal),
            str(output),
            ConvertConfig(
                input_path=str(gtfs_minimal),
                output_path=str(output),
            ),
        )

    benchmark(do_convert)


@pytest.mark.benchmark
def test_bench_convert_branching(gtfs_branching: Path, tmp_path: Path, benchmark: object) -> None:
    """Benchmark conversion of branching fixture."""

    def do_convert() -> None:
        output = tmp_path / "bench_branching"
        output.mkdir(exist_ok=True)
        convert(
            str(gtfs_branching),
            str(output),
            ConvertConfig(
                input_path=str(gtfs_branching),
                output_path=str(output),
            ),
        )

    benchmark(do_convert)
