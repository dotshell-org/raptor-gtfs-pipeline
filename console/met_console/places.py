"""Stops grouped into places, and a forgiving search over them.

A place is every stop bearing one exact name. That is what the engine itself treats as one
place (it links same-name stops), and france-live's renaming keeps a name within one town.
Searching ignores case, accents and punctuation, matches the commune too, and ranks exact
names, then prefixes, then the places served by most stops.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .names import name_key, short_commune


@dataclass
class Place:
    name: str
    ids: list[int]
    lat: float
    lon: float
    commune: str = ""

    @property
    def key(self) -> str:
        return name_key(self.name)

    def label(self) -> str:
        commune = f"  · {self.commune}" if self.commune and self.commune.lower() not in self.name.lower() else ""
        stops = f"  ({len(self.ids)} arrêts)" if len(self.ids) > 1 else ""
        return f"{self.name}{commune}{stops}"


class PlaceIndex:
    def __init__(self, stops: list[tuple[int, str, float, float]]):
        groups: dict[str, list] = {}
        for stop_id, name, lat, lon in stops:
            group = groups.setdefault(name, [[], 0.0, 0.0])
            group[0].append(stop_id)
            group[1] += lat
            group[2] += lon
        self.places = [Place(name, ids, lat / len(ids), lon / len(ids))
                       for name, (ids, lat, lon) in sorted(groups.items())]
        self._keys = [p.key for p in self.places]
        self._with_commune = list(self._keys)  # key + commune key, filled by attach_communes

    def __len__(self) -> int:
        return len(self.places)

    def fingerprint(self) -> str:
        """Names and positions of the places: what their communes depend on."""
        digest = hashlib.sha256()
        for p in self.places:
            digest.update(f"{p.name}\t{p.lat:.5f}\t{p.lon:.5f}\n".encode())
        return digest.hexdigest()[:16]

    def attach_communes(self, cache_dir: Path | None = None, lookup=None) -> bool:
        """Name the commune of each place, cached by the places' fingerprint: France takes a
        while. `lookup(lats, lons)` gives commune names. True when read from the cache."""
        cache = cache_dir / f"communes-{self.fingerprint()}.json" if cache_dir is not None else None
        names = None
        if cache is not None and cache.exists():
            names = json.loads(cache.read_text(encoding="utf-8"))
            if len(names) != len(self.places):
                names = None
        cached = names is not None
        if names is None:
            names = [short_commune(n) for n in lookup(np.array([p.lat for p in self.places]),
                                                      np.array([p.lon for p in self.places]))]
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                for old in cache.parent.glob("communes-*.json"):  # one version's worth is enough
                    old.unlink(missing_ok=True)
                cache.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
        commune_keys: dict[str, str] = {}
        for i, (place, commune) in enumerate(zip(self.places, names)):
            place.commune = commune
            if commune not in commune_keys:
                commune_keys[commune] = name_key(commune)
            self._with_commune[i] = f"{self._keys[i]} {commune_keys[commune]}"
        return cached

    def search(self, text: str, limit: int = 30) -> list[Place]:
        query = name_key(text)
        if not query:
            return []
        words = query.split()
        ranked = []
        first = words[0]
        for i, both in enumerate(self._with_commune):
            if first not in both:  # cheap filter before the ranking
                continue
            key = self._keys[i]
            if key == query:
                rank = 0
            elif key.startswith(query):
                rank = 1
            elif all(w in key for w in words):
                rank = 2
            elif all(w in both for w in words):
                rank = 3
            else:
                continue
            ranked.append((rank, -len(self.places[i].ids), len(key), i))
        ranked.sort()
        return [self.places[i] for *_, i in ranked[:limit]]

    def random_pair(self, rng: random.Random, min_km: float = 2.0, max_km: float = 40.0) -> tuple[Place, Place]:
        """Two places a reasonable trip apart: a uniform pair across France rarely connects."""
        lat = np.array([p.lat for p in self.places])
        lon = np.array([p.lon for p in self.places])
        for _ in range(50):
            a = self.places[rng.randrange(len(self.places))]
            dy = (lat - a.lat) * 111.0
            dx = (lon - a.lon) * 111.0 * np.cos(np.radians(a.lat))
            km = np.hypot(dx, dy)
            candidates = np.flatnonzero((km >= min_km) & (km <= max_km))
            if len(candidates):
                return a, self.places[int(candidates[rng.randrange(len(candidates))])]
        a, b = rng.sample(self.places, 2)
        return a, b
