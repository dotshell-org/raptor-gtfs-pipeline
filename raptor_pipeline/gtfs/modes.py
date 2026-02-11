"""Custom mode configurations for specific transit agencies."""

import logging
import re
from datetime import datetime

from raptor_pipeline.gtfs.models import ServicePeriod
from raptor_pipeline.gtfs.reader import GTFSReader

logger = logging.getLogger(__name__)


def analyze_lyon_periods(reader: GTFSReader) -> list[ServicePeriod]:
    """
    Analyze calendar data for Lyon TCL and group into 4 periods:
    - school_on_weekdays: Weekdays during school periods
    - school_off_weekdays: Weekdays during school holidays
    - saturday: Saturday service
    - sunday: Sunday service
    
    TCL service_id patterns (dash-separated: PREFIX-SEGMENT-PREFIX):
    The last character of the middle segment determines the period type:
    - ...M-... = School period (école)         e.g., -042AM-, -080CM-, -0805M-
    - ...V-... = Vacation period (vacances)    e.g., -042AV-, -080CV-, -0805V-
    - ...W-... = Winter/holiday period         e.g., -006AW-, -040AW-
    - ...N-... = Transitional/night service
    - ...P-... = Special period

    The middle segment varies in length (3-4 alphanumeric chars + optional letter + type).
    Some services use "chouette:TimeTable:..." UUIDs with no dash pattern (typically metro).

    JD lines (school-only routes) are identified by route_short_name starting with "JD"
    """
    if not reader.calendar:
        logger.warning("No calendar data found for Lyon mode")
        return []
    
    logger.info("Analyzing Lyon TCL periods (school_on/school_off/saturday/sunday)")
    
    # Get all JD route IDs (school-only routes)
    jd_routes = set()
    for route in reader.routes:
        route_short_name = route.route_short_name
        if route_short_name and (route_short_name.startswith('JD') or '-JD' in route_short_name):
            jd_routes.add(route.route_id)
    
    logger.info(f"Identified {len(jd_routes)} JD (school-only) routes")
    
    # Map service_id to route for JD detection
    service_to_routes = {}
    for trip in reader.trips:
        if trip.service_id not in service_to_routes:
            service_to_routes[trip.service_id] = set()
        service_to_routes[trip.service_id].add(trip.route_id)
    
    # Categorize services
    school_on_weekdays = set()
    school_off_weekdays = set()
    saturdays = set()
    sundays = set()
    
    # Patterns for TCL service_id (dash-separated format: PREFIX-SEGMENT-PREFIX)
    # The last character of the middle segment is the type indicator.
    # Middle segment: variable-length alphanumeric, e.g., 042A, 080C, 0805, 2027
    school_weekday_pattern = re.compile(r'-[0-9A-Za-z]+M-')   # ends with M = school
    vacation_weekday_pattern = re.compile(r'-[0-9A-Za-z]+[VW]-')  # ends with V/W = vacation

    unmatched_weekday_services = []

    for cal in reader.calendar:
        service_id = cal.service_id

        # Check if this service is for JD routes
        routes_for_service = service_to_routes.get(service_id, set())
        is_jd_only = routes_for_service and routes_for_service.issubset(jd_routes)

        has_weekday = (cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday)
        has_saturday = cal.saturday
        has_sunday = cal.sunday

        # Determine if this is a school or vacation service based on service_id pattern
        is_school_service = bool(school_weekday_pattern.search(service_id))
        is_vacation_service = bool(vacation_weekday_pattern.search(service_id))

        # Categorize weekday services
        if has_weekday:
            if is_jd_only:
                # JD routes ONLY go in school_on
                school_on_weekdays.add(service_id)
            elif is_vacation_service:
                school_off_weekdays.add(service_id)
            elif is_school_service:
                school_on_weekdays.add(service_id)
            else:
                # No dash-pattern matched (chouette:... UUIDs, etc.)
                # These services run regardless of school periods → include in BOTH
                school_on_weekdays.add(service_id)
                school_off_weekdays.add(service_id)
                unmatched_weekday_services.append(service_id)

        # Weekend services
        if has_saturday:
            saturdays.add(service_id)
        if has_sunday:
            sundays.add(service_id)

    if unmatched_weekday_services:
        logger.info(
            f"  {len(unmatched_weekday_services)} weekday service(s) with no "
            f"school/vacation pattern → included in both periods"
        )
    
    periods = []
    
    if school_on_weekdays:
        periods.append(
            ServicePeriod(
                name="school_on_weekdays",
                service_ids=list(school_on_weekdays),
                description="Weekdays during school periods",
            )
        )
    
    if school_off_weekdays:
        periods.append(
            ServicePeriod(
                name="school_off_weekdays",
                service_ids=list(school_off_weekdays),
                description="Weekdays during school holidays",
            )
        )
    
    if saturdays:
        periods.append(
            ServicePeriod(
                name="saturday",
                service_ids=list(set(saturdays)),
                description="Saturday service",
            )
        )
    
    if sundays:
        periods.append(
            ServicePeriod(
                name="sunday",
                service_ids=list(set(sundays)),
                description="Sunday service",
            )
        )
    
    logger.info(f"Lyon mode: Identified {len(periods)} service periods")
    for period in periods:
        logger.info(
            f"  - {period.name}: {len(period.service_ids)} service(s) - {period.description}"
        )
    
    return periods


# Available modes
MODES = {
    "auto": None,  # Automatic detection (default)
    "lyon": analyze_lyon_periods,
}


def get_mode_analyzer(mode: str):
    """Get the analyzer function for a specific mode."""
    if mode not in MODES:
        available = ", ".join(MODES.keys())
        raise ValueError(f"Unknown mode '{mode}'. Available modes: {available}")
    
    return MODES[mode]
