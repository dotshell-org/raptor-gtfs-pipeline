#!/usr/bin/env python3
"""
Standalone runner for the RAPTOR GTFS pipeline — Lyon TCL profile.

Usage:
    uv run python run_lyon.py --input GTFS_TCL.zip --output ./raptor_data_lyon
    uv run python run_lyon.py --input GTFS_TCL.zip --output ./raptor_data_lyon -v
"""
import argparse
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.ConvertConfig import ConvertConfig
from src.gtfs.models.ServicePeriod import ServicePeriod
from src.PipelineConverter import PipelineConverter

# ---------------------------------------------------------------------------
# Lyon-specific period detection
# ---------------------------------------------------------------------------

def analyze_lyon_periods(reader: GTFSReader) -> list[ServicePeriod]:
    """
    Classify TCL Lyon services into 4 periods:
      - school_on_weekdays  : weekdays during school periods
      - school_off_weekdays : weekdays during school holidays
      - saturday
      - sunday

    Logic:
      - Routes whose short name starts with "JD" or contains "-JD" are school-only.
      - service_id ending with "-M-" (regex) → school period weekday service.
      - service_id ending with "-V-" or "-W-" → vacation/holiday weekday service.
      - Services running all 7 days appear in both weekday periods.
    """
    logger = logging.getLogger(__name__)

    if not reader.calendar:
        logger.warning("No calendar data found — Lyon mode requires calendar.txt")
        return []

    logger.info("Analyzing Lyon TCL periods (school_on / school_off / saturday / sunday)")

    # Identify JD (school-only) routes
    jd_routes: set[str] = {
        route.route_id
        for route in reader.routes
        if route.route_short_name and (
            route.route_short_name.startswith("JD")
            or "-JD" in route.route_short_name
        )
    }
    logger.info(f"  {len(jd_routes)} JD (school-only) routes identified")

    # Map service_id → set of route_ids
    service_to_routes: dict[str, set[str]] = {}
    for trip in reader.trips:
        service_to_routes.setdefault(trip.service_id, set()).add(trip.route_id)

    school_weekday_pattern = re.compile(r"-[0-9A-Za-z]+M-")
    vacation_weekday_pattern = re.compile(r"-[0-9A-Za-z]+[VW]-")

    school_on: set[str] = set()
    school_off: set[str] = set()
    saturdays: set[str] = set()
    sundays: set[str] = set()

    for cal in reader.calendar:
        sid = cal.service_id
        routes_for_service = service_to_routes.get(sid, set())
        is_jd_only = bool(routes_for_service) and routes_for_service.issubset(jd_routes)

        has_weekday = cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday
        is_all_week = (
            cal.monday and cal.tuesday and cal.wednesday
            and cal.thursday and cal.friday and cal.saturday and cal.sunday
        )
        is_school = bool(school_weekday_pattern.search(sid))
        is_vacation = bool(vacation_weekday_pattern.search(sid))

        if has_weekday:
            if is_jd_only:
                school_on.add(sid)
            elif is_all_week:
                school_on.add(sid)
                school_off.add(sid)
            elif is_vacation:
                school_off.add(sid)
            elif is_school:
                school_on.add(sid)
            else:
                # No recognisable pattern → include in both
                school_on.add(sid)
                school_off.add(sid)

        if cal.saturday:
            saturdays.add(sid)
        if cal.sunday:
            sundays.add(sid)

    periods: list[ServicePeriod] = []
    if school_on:
        periods.append(ServicePeriod(
            name="school_on_weekdays",
            service_ids=list(school_on),
            description="Weekdays during school periods",
        ))
    if school_off:
        periods.append(ServicePeriod(
            name="school_off_weekdays",
            service_ids=list(school_off),
            description="Weekdays during school holidays",
        ))
    if saturdays:
        periods.append(ServicePeriod(
            name="saturday",
            service_ids=list(saturdays),
            description="Saturday service",
        ))
    if sundays:
        periods.append(ServicePeriod(
            name="sunday",
            service_ids=list(sundays),
            description="Sunday service",
        ))

    logger.info(f"Lyon profile: {len(periods)} periods identified")
    for p in periods:
        logger.info(f"  - {p.name}: {len(p.service_ids)} service(s)")

    return periods


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(input_path_str: str, output_path_str: str, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    input_path = Path(input_path_str)
    output_path = Path(output_path_str)

    temp_dir = None
    try:
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            logger.info(f"Extracting GTFS ZIP: {input_path}")
            temp_dir = tempfile.mkdtemp(prefix="raptor_gtfs_lyon_")

            with zipfile.ZipFile(input_path, "r") as zf:
                zf.extractall(temp_dir)

            txt_files = list(Path(temp_dir).glob("**/*.txt"))
            if not txt_files:
                raise FileNotFoundError("No .txt files found inside the GTFS ZIP archive.")

            actual_input = str(txt_files[0].parent)
        else:
            actual_input = str(input_path)

        config = ConvertConfig(
            input_path=actual_input,
            output_path=str(output_path),
            format="binary",
            compression=True,
            split_by_periods=True,
        )

        manifest = PipelineConverter.convert(
            actual_input,
            str(output_path),
            config,
            period_analyzer=analyze_lyon_periods,
        )

        logger.info("\nConversion successful!")
        logger.info(f"Output: {output_path}")
        logger.info(f"Stats: {manifest.stats}")

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "RAPTOR GTFS pipeline — Lyon TCL profile "
            "(school_on / school_off / saturday / sunday)"
        )
    )
    parser.add_argument(
        "--input",
        default="profiles/gtfs/GTFS_TCL.zip",
        help="Path to GTFS directory or ZIP file (default: profiles/gtfs/GTFS_TCL.zip)",
    )
    parser.add_argument(
        "--output",
        default="profiles/output/lyon",
        help="Output directory (default: profiles/output/lyon)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    run(args.input, args.output, args.verbose)


if __name__ == "__main__":
    main()
