"""Administrative boundaries: which region, which commune, inside mainland France or not.

Etalab's contours (simplified at 100 m) are downloaded once into data/geo/. The vintage
is pinned so that a rerun assigns the same communes and clips at the same borders.

Distances in this package are computed on a local projection: x = R·lon·cos(lat),
y = R·lat, in metres. It is exact enough for what it measures (a few hundred metres
between stops) and needs nothing beyond numpy.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import numpy as np
import requests
import shapely
from shapely.geometry import shape

from .catalog import BENCHMARK_DIR

GEO_DIR = BENCHMARK_DIR / "data" / "geo"
CONTOURS_URL = "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2025/geojson/{name}.geojson"
EARTH_RADIUS_M = 6_371_000.0

#: The 13 regions of mainland France (Corsica included). Overseas regions are not merged.
MAINLAND_REGIONS = ("11", "24", "27", "28", "32", "44", "52", "53", "75", "76", "84", "93", "94")

#: Simplified coastlines cut through harbours: a ferry pier or a seafront stop can fall a
#: few hundred metres outside them. Points this close to a polygon still count as inside.
EDGE_TOLERANCE_M = 2_000.0


def project(lat, lon) -> np.ndarray:
    """(n, 2) metres on the local projection used for every distance in the benchmark."""
    lat_r = np.radians(np.asarray(lat, dtype=float))
    lon_r = np.radians(np.asarray(lon, dtype=float))
    return np.column_stack((EARTH_RADIUS_M * lon_r * np.cos(lat_r), EARTH_RADIUS_M * lat_r))


def _metres_to_degrees(metres: float) -> float:
    return metres / 111_000.0


def _fetch(name: str, geo_dir: Path = GEO_DIR) -> Path:
    path = geo_dir / f"{name}.geojson"
    if not path.exists():
        geo_dir.mkdir(parents=True, exist_ok=True)
        response = requests.get(CONTOURS_URL.format(name=name), timeout=(30, 300),
                                headers={"User-Agent": "raptor-gtfs-pipeline-benchmark"})
        response.raise_for_status()
        json.loads(response.content)  # refuse to cache anything but JSON
        temporary = path.with_name(path.name + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(path)
    return path


def _features(name: str) -> list[dict]:
    with _fetch(name).open(encoding="utf-8") as handle:
        return json.load(handle)["features"]


@functools.cache
def regions() -> dict[str, shapely.Geometry]:
    """Mainland regions by INSEE code, prepared for fast point queries."""
    result = {}
    for feature in _features("regions-100m"):
        code = str(feature["properties"]["code"])
        if code in MAINLAND_REGIONS:
            # Simplification at 100 m leaves self-intersections on jagged coasts (Brittany),
            # which unions refuse: repair first.
            geometry = shapely.make_valid(shape(feature["geometry"]))
            shapely.prepare(geometry)
            result[code] = geometry
    missing = set(MAINLAND_REGIONS) - set(result)
    if missing:
        raise RuntimeError(f"regions missing from the contours: {sorted(missing)}")
    return result


@functools.cache
def region_area(code: str) -> shapely.Geometry:
    """One region, widened by EDGE_TOLERANCE_M."""
    geometry = regions()[code].buffer(_metres_to_degrees(EDGE_TOLERANCE_M))
    shapely.prepare(geometry)
    return geometry


@functools.cache
def mainland() -> shapely.Geometry:
    """Mainland France (Corsica included), widened by EDGE_TOLERANCE_M."""
    geometry = shapely.union_all(list(regions().values())).buffer(_metres_to_degrees(EDGE_TOLERANCE_M))
    shapely.prepare(geometry)
    return geometry


def inside(area: shapely.Geometry, lat, lon) -> np.ndarray:
    """Boolean mask of the points (lat, lon arrays) inside `area`."""
    return shapely.contains_xy(area, np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))


@functools.cache
def _communes() -> tuple[shapely.STRtree, list[str]]:
    geometries, names = [], []
    for feature in _features("communes-100m"):
        geometries.append(shape(feature["geometry"]))
        names.append(feature["properties"]["nom"])
    return shapely.STRtree(geometries), names


def commune_names(lat, lon) -> list[str]:
    """The commune each point falls in; the nearest one for a point at sea or on a border."""
    tree, names = _communes()
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
