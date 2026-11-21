"""Address search, as Pelo does it: the public Photon geocoder (komoot), no key.

Same request and same reading as Pelo's GeocodingRepository: wait for 3 characters, ask for
8 results and keep 6, label a result by its name (a place) or "number street", detail it
with the rest of the address, drop duplicates, keep Photon's order, and fail silently (offline,
slow, rate-limited: the address section is just empty, stop search keeps working).

Two changes for a France-wide network: Pelo keeps results within 80 km of its city, here
the search is limited to mainland France (Photon's bbox, then the country code); and the
search leans towards a point when there is one (the other end of the trip already chosen),
as Pelo leans towards its city centre.

What leaves the machine: the typed text and that point, to photon.komoot.io, with a generic
User-Agent. Answers are cached on disk so the same text is asked once.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "met-console"
MIN_QUERY_LENGTH = 3
DEFAULT_LIMIT = 6
FETCH_LIMIT = 8
TIMEOUT_S = 5.0
MAINLAND_BBOX = (-5.3, 41.2, 9.7, 51.2)  # lon_min, lat_min, lon_max, lat_max


@dataclass(frozen=True)
class Address:
    """A geocoded point: what the engine receives instead of stop ids."""

    label: str
    detail: str | None
    lat: float
    lon: float

    @property
    def name(self) -> str:
        return self.label

    def option_text(self) -> str:
        return f"⌂ {self.label}" + (f"  · {self.detail}" if self.detail else "")

    def endpoint(self) -> dict:
        return {"lat": self.lat, "lon": self.lon, "label": self.label}


def _in_box(lat: float, lon: float, box=MAINLAND_BBOX) -> bool:
    return box[1] <= lat <= box[3] and box[0] <= lon <= box[2]


def feature_to_address(feature: dict) -> Address | None:
    """One Photon feature as Pelo labels it, or None when unusable or outside mainland France."""
    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coordinates) < 2:
        return None
    lon, lat = float(coordinates[0]), float(coordinates[1])
    properties = feature.get("properties") or {}
    country = properties.get("countrycode")
    if (country and country.upper() != "FR") or not _in_box(lat, lon):
        return None
    street_line = " ".join(p for p in (properties.get("housenumber"), properties.get("street")) if p) or None
    name = properties.get("name")
    label = name or street_line
    if not label:
        return None
    city_line = " ".join(p for p in (properties.get("postcode"), properties.get("city")) if p) or None
    detail = ", ".join(p for p in (street_line if name else None, city_line) if p) or None
    return Address(label, detail, lat, lon)


def parse_photon(answer: dict, limit: int = DEFAULT_LIMIT) -> list[Address]:
    seen, found = set(), []
    for feature in answer.get("features", []):
        address = feature_to_address(feature)
        if address is None or (address.label, address.detail) in seen:
            continue
        seen.add((address.label, address.detail))
        found.append(address)
        if len(found) == limit:
            break
    return found


def _http_get(url: str, params: dict) -> dict:
    import requests

    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()


class Geocoder:
    """Photon search with a small disk cache. Thread-safe: the explorer calls it from workers."""

    def __init__(self, cache: Path | None = None, url: str = PHOTON_URL,
                 get: Callable[[str, dict], dict] = _http_get):
        self.url, self._get, self._cache_path = url, get, cache
        self._lock = threading.Lock()
        self._cache: dict[str, list] = {}
        if cache is not None and cache.exists():
            try:
                self._cache = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}

    @staticmethod
    def _key(text: str, near: tuple[float, float] | None) -> str:
        bias = f"{near[0]:.2f},{near[1]:.2f}" if near else "-"  # ~1 km: close enough for a bias
        return f"{text.strip().lower()}|{bias}"

    def search(self, text: str, near: tuple[float, float] | None = None, limit: int = DEFAULT_LIMIT) -> list[Address]:
        text = text.strip()
        if len(text) < MIN_QUERY_LENGTH:
            return []
        key = self._key(text, near)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return [Address(*row) for row in cached][:limit]
        params = {"q": text, "lang": "fr", "limit": FETCH_LIMIT,
                  "bbox": ",".join(str(v) for v in MAINLAND_BBOX)}
        if near:
            params["lat"], params["lon"] = f"{near[0]:.4f}", f"{near[1]:.4f}"
        try:
            found = parse_photon(self._get(self.url, params), DEFAULT_LIMIT)
        except Exception:  # offline, timeout, 429, bad JSON: no addresses, as in Pelo
            return []
        with self._lock:
            self._cache[key] = [[a.label, a.detail, a.lat, a.lon] for a in found]
            self._save()
        return found[:limit]

    def _save(self) -> None:
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
