import logging
from collections import defaultdict

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.ServicePeriod import ServicePeriod

logger = logging.getLogger(__name__)


class CalendarAnalyzer:
    """Analyze calendar data and group services into periods."""

    @staticmethod
    def analyze_service_periods(reader: GTFSReader) -> list[ServicePeriod]:
        """
        Analyze calendar data and group services into periods.
        
        Returns a list of ServicePeriod objects, each representing a schedule pattern
        (e.g., weekday, weekend, school period, holidays).
        """
        if not reader.calendar and not reader.calendar_dates:
            logger.warning("No calendar data found, cannot split by service periods")
            return []
        
        logger.info("Analyzing service periods from calendar data")
        
        # Group services by their day-of-week pattern
        patterns: dict[tuple[bool, ...], list[str]] = defaultdict(list)
        
        for cal in reader.calendar:
            pattern = (
                cal.monday,
                cal.tuesday,
                cal.wednesday,
                cal.thursday,
                cal.friday,
                cal.saturday,
                cal.sunday,
            )
            patterns[pattern].append(cal.service_id)
        
        # Create service periods based on patterns
        periods: list[ServicePeriod] = []
        
        # Weekday pattern (Mon-Fri)
        weekday_pattern = (True, True, True, True, True, False, False)
        if weekday_pattern in patterns:
            periods.append(
                ServicePeriod(
                    name="weekday",
                    service_ids=patterns[weekday_pattern],
                    description="Monday to Friday service",
                )
            )
            del patterns[weekday_pattern]
        
        # Saturday pattern
        saturday_pattern = (False, False, False, False, False, True, False)
        if saturday_pattern in patterns:
            periods.append(
                ServicePeriod(
                    name="saturday",
                    service_ids=patterns[saturday_pattern],
                    description="Saturday service",
                )
            )
            del patterns[saturday_pattern]
        
        # Sunday pattern
        sunday_pattern = (False, False, False, False, False, False, True)
        if sunday_pattern in patterns:
            periods.append(
                ServicePeriod(
                    name="sunday",
                    service_ids=patterns[sunday_pattern],
                    description="Sunday and holidays service",
                )
            )
            del patterns[sunday_pattern]
        
        # Weekend pattern (Sat-Sun)
        weekend_pattern = (False, False, False, False, False, True, True)
        if weekend_pattern in patterns:
            periods.append(
                ServicePeriod(
                    name="weekend",
                    service_ids=patterns[weekend_pattern],
                    description="Weekend service",
                )
            )
            del patterns[weekend_pattern]
        
        # All week pattern (every day)
        allweek_pattern = (True, True, True, True, True, True, True)
        if allweek_pattern in patterns:
            periods.append(
                ServicePeriod(
                    name="daily",
                    service_ids=patterns[allweek_pattern],
                    description="Daily service (all days)",
                )
            )
            del patterns[allweek_pattern]
        
        # Everything that didn't match a standard day-type goes into a single
        # "other" bucket — never dozens of numbered custom_N folders.
        if patterns:
            other_service_ids: list[str] = []
            for _pattern, service_ids in sorted(patterns.items()):
                other_service_ids.extend(service_ids)
            periods.append(
                ServicePeriod(
                    name="other",
                    service_ids=other_service_ids,
                    description=(
                        f"{len(patterns)} non-standard weekly pattern(s), "
                        f"{len(other_service_ids)} service(s) — "
                        "pass a profile (--profile) to classify these"
                    ),
                )
            )
        
        # If no calendar.txt, but calendar_dates.txt exists, group by service_id
        if not periods and reader.calendar_dates:
            logger.warning(
                "No calendar.txt found — grouping all calendar_dates services into "
                "'other'; pass a profile (--profile) to split them meaningfully"
            )
            services_from_dates = {cd.service_id for cd in reader.calendar_dates}
            
            periods.append(
                ServicePeriod(
                    name="other",
                    service_ids=sorted(services_from_dates),
                    description=f"{len(services_from_dates)} service(s) from calendar_dates.txt",
                )
            )
        
        logger.info(f"Identified {len(periods)} service periods")
        for period in periods:
            logger.info(
                f"  - {period.name}: {len(period.service_ids)} service(s) - {period.description}"
            )
        
        return periods

    @staticmethod
    def get_trips_for_period(reader: GTFSReader, period: ServicePeriod) -> set[str]:
        """
        Get all trip IDs that belong to a specific service period.
        
        Args:
            reader: GTFSReader with loaded data
            period: ServicePeriod to filter trips for
        
        Returns:
            Set of trip IDs belonging to this period
        """
        trip_ids = set()
        
        for trip in reader.trips:
            if trip.service_id in period.service_ids:
                trip_ids.add(trip.trip_id)
        
        return trip_ids
