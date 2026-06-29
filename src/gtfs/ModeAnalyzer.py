import logging
import re
from typing import Any, Callable

from src.gtfs.models.ServicePeriod import ServicePeriod
from src.gtfs.GTFSReader import GTFSReader

logger = logging.getLogger(__name__)


class ModeAnalyzer:
    """Custom mode configurations for specific transit agencies."""

    @staticmethod
    def analyze_lyon_periods(reader: GTFSReader) -> list[ServicePeriod]:
        """
        Analyze calendar data for Lyon TCL and group into 4 periods.
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
        service_to_routes: dict[str, set[str]] = {}
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
        school_weekday_pattern = re.compile(r'-[0-9A-Za-z]+M-')   # ends with M = school
        vacation_weekday_pattern = re.compile(r'-[0-9A-Za-z]+[VW]-')  # ends with V/W = vacation
        
        unmatched_weekday_services = []
        all_week_services = []
        
        for cal in reader.calendar:
            service_id = cal.service_id
            
            # Check if this service is for JD routes
            routes_for_service = service_to_routes.get(service_id, set())
            is_jd_only = routes_for_service and routes_for_service.issubset(jd_routes)
            
            has_weekday = (cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday)
            has_saturday = cal.saturday
            has_sunday = cal.sunday
            
            # Services running all 7 days
            is_all_week = (cal.monday and cal.tuesday and cal.wednesday and
                           cal.thursday and cal.friday and cal.saturday and cal.sunday)
            
            is_school_service = bool(school_weekday_pattern.search(service_id))
            is_vacation_service = bool(vacation_weekday_pattern.search(service_id))
            
            # Categorize weekday services
            if has_weekday:
                if is_jd_only:
                    school_on_weekdays.add(service_id)
                elif is_all_week:
                    school_on_weekdays.add(service_id)
                    school_off_weekdays.add(service_id)
                    all_week_services.append(service_id)
                elif is_vacation_service:
                    school_off_weekdays.add(service_id)
                elif is_school_service:
                    school_on_weekdays.add(service_id)
                else:
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
        
        if all_week_services:
            logger.info(
                f"  {len(all_week_services)} all-week service(s) (Mon-Sun) "
                f"→ included in both school_on and school_off periods"
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

    # MODES mappings registry
    MODES: dict[str, Callable[[GTFSReader], list[ServicePeriod]] | None] = {
        "auto": None,
        "lyon": analyze_lyon_periods,
    }

    @staticmethod
    def get_mode_analyzer(mode: str) -> Callable[[GTFSReader], list[ServicePeriod]] | None:
        """Get the analyzer function for a specific mode."""
        if mode not in ModeAnalyzer.MODES:
            available = ", ".join(ModeAnalyzer.MODES.keys())
            raise ValueError(f"Unknown mode '{mode}'. Available modes: {available}")
        
        return ModeAnalyzer.MODES[mode]
