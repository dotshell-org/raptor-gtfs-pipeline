"""Communes and the outline of France, for naming places and drawing the map.

Etalab's 2025 contours (simplified at 100 m), the vintage met-dataset-server names stops with,
downloaded once into the cache and checked against their SHA-256.
"""

from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

import numpy as np

CONTOURS = {
    "regions-100m": ("https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2025/geojson/regions-100m.geojson",
                     "af18f6cb83eaf081168d009964f8e4aa8ae1a80ef5388149201e95e015020652"),
    "communes-100m": ("https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2025/geojson/communes-100m.geojson",
                      "3a5666ec71eddf7354362f3141d53507f976990a43e8994b5582bbd55a58157c"),
}
#: The 13 regions of mainland France (Corsica included).
MAINLAND_REGIONS = ("11", "24", "27", "28", "32", "44", "52", "53", "75", "76", "84", "93", "94")
USER_AGENT = "met-console"


def fetch(name: str, geo_dir: Path) -> Path:
    """The contour file, downloaded once and checked."""
    url, sha = CONTOURS[name]
    path = geo_dir / f"{name}.geojson"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
        return path
    import requests

    geo_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=(30, 300), headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != sha:
        raise RuntimeError(f"{name}: SHA-256 {digest}, {sha} expected")
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(response.content)
    temporary.replace(path)
    return path


def _features(name: str, geo_dir: Path) -> list[dict]:
    with fetch(name, geo_dir).open(encoding="utf-8") as handle:
        return json.load(handle)["features"]


@functools.cache
def mainland(geo_dir: Path):
    """Mainland France (Corsica included) as one shapely geometry."""
    import shapely
    from shapely.geometry import shape

    parts = [shapely.make_valid(shape(f["geometry"])) for f in _features("regions-100m", geo_dir)
             if str(f["properties"]["code"]) in MAINLAND_REGIONS]
    return shapely.union_all(parts)


@functools.cache
def _communes(geo_dir: Path):
    import shapely
    from shapely.geometry import shape

    geometries, names = [], []
    for feature in _features("communes-100m", geo_dir):
        geometries.append(shape(feature["geometry"]))
        names.append(feature["properties"]["nom"])
    return shapely.STRtree(geometries), names


def commune_names(geo_dir: Path, lat, lon) -> list[str]:
    """The commune each point falls in; the nearest one for a point at sea or on a border."""
    import shapely

    tree, names = _communes(geo_dir)
    points = shapely.points(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    result: list[str | None] = [None] * len(points)
    point_index, commune_index = tree.query(points, predicate="within")
    for p, c in zip(point_index, commune_index):
        if result[p] is None:
            result[p] = names[c]
    orphans = [i for i, name in enumerate(result) if name is None]
    if orphans:
        nearest = tree.query_nearest(points[orphans], return_distance=False, all_matches=False)
        for p, c in zip(nearest[0], nearest[1]):
            result[orphans[p]] = names[c]
    return result  # type: ignore[return-value]
