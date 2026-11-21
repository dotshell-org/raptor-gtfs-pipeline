"""The version dataset-sync installed, and what its files say.

    <data>/france-live/installed.json      the latest.json of the installed version
    <data>/france-live/<version>/          its files: dataset.json, horizon.json, sources.json,
                                           licence.json, and one folder per day type

dataset-sync owns <data>/france-live: anything else put there goes at the next update.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from .daytypes import DAY_TYPES, Plan


@dataclass
class Installed:
    root: Path
    version: str
    latest: dict

    @property
    def dir(self) -> Path:
        return self.root / self.version

    def read(self, name: str):
        """One of the version's JSON files, or None."""
        path = self.dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def plan(self) -> Plan | None:
        path = self.dir / "horizon.json"
        return Plan.read(path) if path.exists() else None

    def created_at(self) -> dt.datetime | None:
        text = (self.read("dataset.json") or {}).get("createdAt") or self.latest.get("created_at")
        try:  # "2026-11-21T03:04:12.219530004Z": the seconds are enough
            return dt.datetime.fromisoformat(text[:19]).replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            return None

    def day_types(self) -> list[str]:
        found = [p.name for p in self.dir.iterdir() if p.is_dir() and (p / "routes.bin").exists()]
        return sorted(found, key=lambda n: DAY_TYPES.index(n) if n in DAY_TYPES else 99)

    def size(self, sub: str = "") -> int:
        base = self.dir / sub if sub else self.dir
        return sum(p.stat().st_size for p in base.rglob("*") if p.is_file())


def installed(root: Path) -> Installed | None:
    """The installed version, or None when there is none (or its folder is missing)."""
    try:
        latest = json.loads((root / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = latest.get("version")
    if not version or not (root / version).is_dir():
        return None
    return Installed(root, version, latest)


def megabytes(n: int | None) -> str:
    if n is None:
        return "–"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} Ko".replace(".", ",")
    return f"{n / 1024 / 1024:.1f} Mo".replace(".", ",")
