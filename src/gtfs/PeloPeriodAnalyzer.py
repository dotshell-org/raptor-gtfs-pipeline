import logging
import re

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.ServicePeriod import ServicePeriod

logger = logging.getLogger(__name__)

# School-term vs holiday weekday signals (TCL / Pelo convention). Feeds that
# don't use them simply fall back to identical school_on/school_off data.
_SCHOOL_WEEKDAY = re.compile(r"-[0-9A-Za-z]+M-")
_VACATION_WEEKDAY = re.compile(r"-[0-9A-Za-z]+[VW]-")


class PeloPeriodAnalyzer:
    """Split services into the four periods the Pelo app expects.

    Produces exactly ``school_on_weekdays``, ``school_off_weekdays``,
    ``saturday`` and ``sunday``. Weekday services are classified into
    school-term vs holiday using, in order:

      1. school-only routes (short name starts with ``JD`` or contains ``-JD``)
         → school_on only;
      2. services running all seven days → both weekday periods;
      3. ``service_id`` matching the holiday pattern → school_off;
      4. ``service_id`` matching the school pattern → school_on;
      5. anything else → both weekday periods.

    On feeds without any school signal, every weekday service lands in both
    periods, so school_on and school_off carry identical data (as the app
    expects when a network has no school split).
    """

    @staticmethod
    def build(reader: GTFSReader) -> list[ServicePeriod]:
        if not reader.calendar:
            logger.warning("Pelo mode requires calendar.txt — no periods produced")
            return []

        jd_routes: set[str] = {
            route.route_id
            for route in reader.routes
            if route.route_short_name
            and (route.route_short_name.startswith("JD") or "-JD" in route.route_short_name)
        }

        service_to_routes: dict[str, set[str]] = {}
        for trip in reader.trips:
            service_to_routes.setdefault(trip.service_id, set()).add(trip.route_id)

        school_on: set[str] = set()
        school_off: set[str] = set()
        saturdays: set[str] = set()
        sundays: set[str] = set()

        for cal in reader.calendar:
            sid = cal.service_id
            routes_for_service = service_to_routes.get(sid, set())
            is_jd_only = bool(routes_for_service) and routes_for_service.issubset(jd_routes)
            has_weekday = (
                cal.monday or cal.tuesday or cal.wednesday or cal.thursday or cal.friday
            )
            is_all_week = all(
                (cal.monday, cal.tuesday, cal.wednesday, cal.thursday,
                 cal.friday, cal.saturday, cal.sunday)
            )

            if has_weekday:
                if is_jd_only:
                    school_on.add(sid)
                elif is_all_week:
                    school_on.add(sid)
                    school_off.add(sid)
                elif _VACATION_WEEKDAY.search(sid):
                    school_off.add(sid)
                elif _SCHOOL_WEEKDAY.search(sid):
                    school_on.add(sid)
                else:
                    school_on.add(sid)
                    school_off.add(sid)

            if cal.saturday:
                saturdays.add(sid)
            if cal.sunday:
                sundays.add(sid)

        specs = [
            ("school_on_weekdays", school_on, "Weekdays during school periods"),
            ("school_off_weekdays", school_off, "Weekdays during school holidays"),
            ("saturday", saturdays, "Saturday service"),
            ("sunday", sundays, "Sunday service"),
        ]
        periods = [
            ServicePeriod(name=name, service_ids=sorted(ids), description=desc)
            for name, ids, desc in specs
            if ids
        ]
        for name, ids, _ in specs:
            if not ids:
                logger.warning(f"Pelo period '{name}' matched no services")

        logger.info(f"Pelo mode → {len(periods)} period(s)")
        return periods
