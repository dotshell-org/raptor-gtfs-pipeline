import logging
import re
from pathlib import Path

import yaml

from src.gtfs.GTFSReader import GTFSReader
from src.gtfs.models.Profile import PeriodRule, Profile
from src.gtfs.models.ServicePeriod import ServicePeriod

logger = logging.getLogger(__name__)

_DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_DAY_ALIASES: dict[str, set[int]] = {
    "weekday": {0, 1, 2, 3, 4},
    "weekdays": {0, 1, 2, 3, 4},
    "weekend": {5, 6},
    "weekends": {5, 6},
    "daily": set(range(7)),
    "everyday": set(range(7)),
    "all": set(range(7)),
}


class ProfileAnalyzer:
    """Build service periods from a declarative YAML profile.

    Usage as the ``period_analyzer`` of ``PipelineConverter.convert``:
        profile = ProfileAnalyzer.load("profiles/lyon.yaml")
        convert(..., period_analyzer=partial(ProfileAnalyzer.build, profile))
    """

    @staticmethod
    def load(path: str) -> Profile:
        """Load and validate a YAML profile."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Profile '{path}' must be a YAML mapping")
        return Profile(**data)

    @staticmethod
    def _parse_days(tokens: list[str]) -> set[int]:
        result: set[int] = set()
        for token in tokens:
            t = token.strip().lower()
            if t in _DAY_ALIASES:
                result |= _DAY_ALIASES[t]
            elif "-" in t:
                start, _, end = t.partition("-")
                start, end = start.strip(), end.strip()
                if start not in _DAY_INDEX or end not in _DAY_INDEX:
                    raise ValueError(f"Invalid day range '{token}'")
                result |= set(range(_DAY_INDEX[start], _DAY_INDEX[end] + 1))
            elif t in _DAY_INDEX:
                result.add(_DAY_INDEX[t])
            else:
                raise ValueError(f"Unknown day token '{token}'")
        return result

    @staticmethod
    def _matches(rule: PeriodRule, service_id: str, active_days: set[int]) -> bool:
        if rule.service_id_matches and not re.search(rule.service_id_matches, service_id):
            return False
        if rule.days and active_days.isdisjoint(ProfileAnalyzer._parse_days(rule.days)):
            return False
        return True

    @staticmethod
    def build(profile: Profile, reader: GTFSReader) -> list[ServicePeriod]:
        """Assign every service to the profile's periods; bucket/drop the rest."""
        # service_id -> active weekday indices (empty when only in calendar_dates,
        # in which case only regex rules can match).
        services: dict[str, set[int]] = {}
        for cal in reader.calendar:
            services[cal.service_id] = {
                i
                for i, active in enumerate(
                    [cal.monday, cal.tuesday, cal.wednesday, cal.thursday,
                     cal.friday, cal.saturday, cal.sunday]
                )
                if active
            }
        for cd in reader.calendar_dates:
            services.setdefault(cd.service_id, set())

        assigned: dict[str, list[str]] = {name: [] for name in profile.periods}
        matched: set[str] = set()
        for service_id, active_days in services.items():
            for name, rule in profile.periods.items():
                if ProfileAnalyzer._matches(rule, service_id, active_days):
                    assigned[name].append(service_id)
                    matched.add(service_id)

        periods: list[ServicePeriod] = []
        for name, ids in assigned.items():
            if ids:
                periods.append(
                    ServicePeriod(
                        name=name,
                        service_ids=sorted(ids),
                        description=profile.periods[name].description
                        or f"Profile period '{name}'",
                    )
                )
            else:
                logger.warning(f"Profile period '{name}' matched no services")

        unmatched = sorted(set(services) - matched)
        if unmatched:
            if profile.unmatched == "other":
                periods.append(
                    ServicePeriod(
                        name="other",
                        service_ids=unmatched,
                        description=f"{len(unmatched)} service(s) not matched by the profile",
                    )
                )
            else:
                preview = ", ".join(unmatched[:10])
                logger.warning(
                    f"{len(unmatched)} service(s) not matched by the profile "
                    f"and dropped: {preview}{'…' if len(unmatched) > 10 else ''}"
                )

        label = profile.network or "profile"
        logger.info(f"Profile '{label}' → {len(periods)} period(s)")
        return periods
