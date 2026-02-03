"""Custom mode configurations for specific transit agencies."""

import logging
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
    
    School periods in France (approximate):
    - Sept to Oct: school on
    - Late Oct to early Nov: school off (Toussaint)
    - Nov to Dec: school on
    - Late Dec to early Jan: school off (Christmas)
    - Jan to Feb: school on
    - Feb: school off (Winter holidays)
    - Mar to Apr: school on
    - Apr: school off (Spring holidays)
    - May to July: school on
    - July-Aug: school off (Summer)
    """
    if not reader.calendar:
        logger.warning("No calendar data found for Lyon mode")
        return []
    
    logger.info("Analyzing Lyon TCL periods (school_on/school_off/saturday/sunday)")
    
    # Define school holiday periods for 2025-2026
    school_holidays = [
        ("20251024", "20251103"),  # Toussaint
        ("20251220", "20260104"),  # Christmas/New Year
        ("20260220", "20260308"),  # Winter (approx)
        ("20260410", "20260426"),  # Spring (approx)
        ("20260704", "20260831"),  # Summer
    ]
    
    def is_school_holiday(start_date: str, end_date: str) -> bool:
        """Check if a service period overlaps with school holidays."""
        for holiday_start, holiday_end in school_holidays:
            # Check overlap
            if not (end_date < holiday_start or start_date > holiday_end):
                return True
        return False
    
    # Categorize services
    school_on_weekdays = []
    school_off_weekdays = []
    saturdays = []
    sundays = []
    
    for cal in reader.calendar:
        # Weekday pattern (M-F)
        if cal.monday and cal.tuesday and cal.wednesday and cal.thursday and cal.friday and not cal.saturday and not cal.sunday:
            if is_school_holiday(cal.start_date, cal.end_date):
                school_off_weekdays.append(cal.service_id)
            else:
                school_on_weekdays.append(cal.service_id)
        
        # Saturday only
        elif cal.saturday and not cal.sunday and not (cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday):
            saturdays.append(cal.service_id)
        
        # Sunday only
        elif cal.sunday and not cal.saturday and not (cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday):
            sundays.append(cal.service_id)
        
        # Custom patterns with weekdays - check if mostly weekdays
        elif (cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday):
            if not (cal.saturday or cal.sunday):
                # It's a weekday service (might be partial week)
                if is_school_holiday(cal.start_date, cal.end_date):
                    school_off_weekdays.append(cal.service_id)
                else:
                    school_on_weekdays.append(cal.service_id)
            elif cal.saturday and not cal.sunday:
                # Weekdays + Saturday, consider as school_on weekday
                if is_school_holiday(cal.start_date, cal.end_date):
                    school_off_weekdays.append(cal.service_id)
                else:
                    school_on_weekdays.append(cal.service_id)
        
        # Saturday + Sunday (weekend pattern)
        elif cal.saturday and cal.sunday:
            saturdays.append(cal.service_id)
            sundays.append(cal.service_id)
    
    periods = []
    
    if school_on_weekdays:
        periods.append(
            ServicePeriod(
                name="school_on_weekdays",
                service_ids=school_on_weekdays,
                description="Weekdays during school periods",
            )
        )
    
    if school_off_weekdays:
        periods.append(
            ServicePeriod(
                name="school_off_weekdays",
                service_ids=school_off_weekdays,
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
