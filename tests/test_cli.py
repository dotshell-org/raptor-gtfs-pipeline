"""Tests for CLI."""

import subprocess
from pathlib import Path


def test_cli_convert_basic(gtfs_minimal: Path, tmp_path: Path) -> None:
    """Test CLI convert command."""
    output = tmp_path / "output"

    result = subprocess.run(
        [
            "python",
            "-m",
            "raptor_pipeline.cli",
            "convert",
            "--input",
            str(gtfs_minimal),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Conversion successful" in result.stdout
    assert (output / "routes.bin").exists()


def test_cli_validate_basic(gtfs_minimal: Path, tmp_path: Path) -> None:
    """Test CLI validate command."""
    output = tmp_path / "output"

    # First convert
    subprocess.run(
        [
            "python",
            "-m",
            "raptor_pipeline.cli",
            "convert",
            "--input",
            str(gtfs_minimal),
            "--output",
            str(output),
        ],
        check=True,
    )

    # Then validate
    result = subprocess.run(
        [
            "python",
            "-m",
            "raptor_pipeline.cli",
            "validate",
            "--input",
            str(output),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Validation successful" in result.stdout


def test_cli_version() -> None:
    """Test CLI version flag."""
    result = subprocess.run(
        ["python", "-m", "raptor_pipeline.cli", "--version"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_cli_help() -> None:
    """Test CLI help."""
    result = subprocess.run(
        ["python", "-m", "raptor_pipeline.cli", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "convert" in result.stdout
    assert "validate" in result.stdout


def test_cli_convert_with_flags(gtfs_minimal: Path, tmp_path: Path) -> None:
    """Test CLI with various flags."""
    output = tmp_path / "output"

    result = subprocess.run(
        [
            "python",
            "-m",
            "raptor_pipeline.cli",
            "convert",
            "--input",
            str(gtfs_minimal),
            "--output",
            str(output),
            "--format",
            "both",
            "--debug-json",
            "true",
            "--compression",
            "true",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (output / "routes.bin").exists()
    assert (output / "routes.json").exists()


def test_cli_convert_invalid_input() -> None:
    """Test CLI with invalid input."""
    result = subprocess.run(
        [
            "python",
            "-m",
            "raptor_pipeline.cli",
            "convert",
            "--input",
            "/nonexistent/path",
            "--output",
            "/tmp/output",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Error" in result.stdout or "Error" in result.stderr
