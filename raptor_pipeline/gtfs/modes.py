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
    
    TCL service_id patterns:
    - xxxx-xxxAM-xxxx = Weekday, School period (école)
    - xxxx-xxxAV-xxxx = Weekday, Vacation period (vacances)
    - xxxx-xxxAW-xxxx = Weekday, Winter/holiday period
    - xxxx-xxxxM-xxxx = Weekend (usually school period)
    - xxxx-xxxxT-xxxx = Weekend transitional/special
    
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
    
    # Patterns for TCL service_id
    school_weekday_pattern = re.compile(r'-\d{3}[AB]?M-')  # e.g., -042AM-, -065AM-, -085BM-
    vacation_weekday_pattern = re.compile(r'-\d{3}A[VW]-')  # e.g., -042AV-, -006AW-
    
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
        
        # If no pattern matched, try to determine from date ranges
        if has_weekday and not is_school_service and not is_vacation_service:
            # Fallback: check if dates fall in typical vacation periods
            # Dec 20 - Jan 5 = Winter vacation, July-Aug = Summer vacation
            # Feb vacation week, Spring vacation (2 weeks in April)
            start_date = str(cal.start_date) if hasattr(cal, 'start_date') else ""
            if start_date:
                month = int(start_date[4:6]) if len(start_date) >= 6 else 0
                # Summer vacation (July-August) or December dates = likely vacation
                if month in (7, 8) or (month == 12 and int(start_date[6:8]) > 20):
                    is_vacation_service = True
                else:
                    is_school_service = True
        
        # Categorize weekday services
        if has_weekday:
            if is_jd_only:
                # JD routes ONLY go in school_on
                school_on_weekdays.add(service_id)
            elif is_vacation_service:
                # Vacation-only service
                school_off_weekdays.add(service_id)
            elif is_school_service:
                # School-only service
                school_on_weekdays.add(service_id)
            else:
                # Unknown pattern - put in both (safest fallback)
                school_on_weekdays.add(service_id)
                school_off_weekdays.add(service_id)
        
        # Weekend services
        if has_saturday:
            saturdays.add(service_id)
        if has_sunday:
            sundays.add(service_id)
    
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
