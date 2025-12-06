"""Pytest configuration and fixtures."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def gtfs_minimal() -> Path:
    """Path to minimal GTFS fixture."""
    return Path(__file__).parent / "fixtures" / "gtfs_minimal"


@pytest.fixture
def gtfs_branching() -> Path:
    """Path to branching GTFS fixture."""
    return Path(__file__).parent / "fixtures" / "gtfs_branching"


@pytest.fixture
def gtfs_edgecases() -> Path:
    """Path to edge cases GTFS fixture."""
    return Path(__file__).parent / "fixtures" / "gtfs_edgecases"


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Temporary output directory."""
    output_dir = tmp_path / "raptor_data"
    output_dir.mkdir()
    yield output_dir
    # Cleanup
    if output_dir.exists():
        shutil.rmtree(output_dir)
