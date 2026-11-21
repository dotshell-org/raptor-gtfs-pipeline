"""Which day type serves a date: the server's horizon.json read with the French calendar.

france-live is one timetable per day type (semaine, samedi, dimanche, sometimes vacances),
each taken from a representative date. A date inside the version's window runs on: Sundays
and public holidays → dimanche; Saturdays → samedi; weekdays in the national school holidays
→ vacances when the version has it; else semaine. The same rule as met-dataset-server's
FrenchCalendar, with the same holidays (config/france-live/settings.yaml there).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

#: National school holidays (every zone at once), as met-dataset-server has them. Yearly update.
SCHOOL_HOLIDAYS = ((dt.date(2026, 12, 19), dt.date(2027, 1, 3)), (dt.date(2027, 7, 3), dt.date(2027, 8, 31)))
DAY_TYPES = ("semaine", "samedi", "dimanche", "vacances")
LABELS = {"semaine": "semaine", "samedi": "samedi", "dimanche": "dimanche et fêtes", "vacances": "vacances scolaires"}


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    return dt.date(year, month, (h + l - 7 * m + 33 * month + 19) % 32)


def public_holidays(year: int) -> set[dt.date]:
    """The 11 public holidays of mainland France."""
    e = easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    return {dt.date(year, m, d) for m, d in fixed} | {e + dt.timedelta(days=1), e + dt.timedelta(days=39),
                                                     e + dt.timedelta(days=50)}


def is_public_holiday(day: dt.date) -> bool:
    return day in public_holidays(day.year)


def in_school_holidays(day: dt.date, holidays=SCHOOL_HOLIDAYS) -> bool:
    return any(start <= day <= end for start, end in holidays)


def day_type(day: dt.date, has_vacances: bool, holidays=SCHOOL_HOLIDAYS) -> str:
    """Which day type's network serves this date (public holidays run as Sundays)."""
    if day.weekday() == 6 or is_public_holiday(day):
        return "dimanche"
    if day.weekday() == 5:
        return "samedi"
    if has_vacances and in_school_holidays(day, holidays):
        return "vacances"
    return "semaine"


@dataclass
class Plan:
    """A version's horizon.json: its window, and each day type's representative date."""

    computed_on: str
    start: str
    end: str
    binding_feed: str | None
    binding_share: float | None
    days: dict[str, str]
    lost: list[dict] = field(default_factory=list)
    feeds: int = 0
    max_feed_share: float = 0.005
    max_lost_share: float = 0.01

    @property
    def window(self) -> tuple[dt.date, dt.date]:
        return dt.date.fromisoformat(self.start), dt.date.fromisoformat(self.end)

    def network_for(self, day: dt.date) -> str | None:
        """The day type serving `day`, or None outside the window."""
        start, end = self.window
        if not start <= day <= end:
            return None
        return day_type(day, "vacances" in self.days)

    @classmethod
    def read(cls, path: Path) -> Plan:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
