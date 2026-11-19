"""A map of France in braille: the outline, and the journey drawn over it.

Each terminal cell holds a braille character, a 2 × 4 grid of dots, so a 60 × 20 cell map
is 120 × 80 dots. Braille dots are close to square on most fonts, which keeps France's
proportions with nothing more than the cos(latitude) factor. A cell has one colour: when
two layers meet, the more important one wins (endpoints, then rides, then walks, then the
outline).
"""

from __future__ import annotations

import functools
import json
import math
from pathlib import Path

import numpy as np
from rich.text import Text

from .backend import Journey

# Dot (x, y) in the 2 × 4 cell -> bit of the braille character (U+2800 + bits).
_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
NETWORK = "#3b3a37"
OUTLINE = "#6b6a66"
WALK = "#c3c2b7"
START = "#1baf7a"
END = "#e34948"
#: Ride colours, in the data-viz palette's categorical order.
RIDES = ("#2a78d6", "#eb6834", "#eda100", "#e87ba4", "#6250d6", "#1baf7a", "#008300", "#e34948")
_PRIORITY = {NETWORK: -1, OUTLINE: 0, WALK: 1, START: 3, END: 3, **{c: 2 for c in RIDES}}
_BIT_TABLE = np.array(_BITS)

FRANCE_BBOX = (-5.3, 41.2, 9.7, 51.2)  # lon_min, lat_min, lon_max, lat_max


class Canvas:
    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = max(cols, 4), max(rows, 2)
        self.width, self.height = self.cols * 2, self.rows * 4
        self.bits = [[0] * self.cols for _ in range(self.rows)]
        self.colour: list[list[str | None]] = [[None] * self.cols for _ in range(self.rows)]

    def dot(self, x: int, y: int, colour: str) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        row, col = y // 4, x // 2
        self.bits[row][col] |= _BITS[y % 4][x % 2]
        current = self.colour[row][col]
        if current is None or _PRIORITY.get(colour, 0) >= _PRIORITY.get(current, 0):
            self.colour[row][col] = colour

    def line(self, x0: float, y0: float, x1: float, y1: float, colour: str) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            t = i / steps
            self.dot(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), colour)

    def scatter(self, xs: np.ndarray, ys: np.ndarray, colour: str) -> None:
        """Many single dots at once (every stop of a network), without a Python loop per dot."""
        xs, ys = np.round(xs).astype(int), np.round(ys).astype(int)
        keep = (xs >= 0) & (xs < self.width) & (ys >= 0) & (ys < self.height)
        xs, ys = xs[keep], ys[keep]
        grid = np.zeros((self.rows, self.cols), dtype=np.int64)
        np.bitwise_or.at(grid, (ys // 4, xs % self.width // 2), _BIT_TABLE[ys % 4, xs % 2])
        for row, col in zip(*np.nonzero(grid)):
            self.bits[row][col] |= int(grid[row, col])
            if self.colour[row][col] is None:
                self.colour[row][col] = colour

    def disc(self, x: float, y: float, colour: str) -> None:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.dot(round(x) + dx, round(y) + dy, colour)

    def render(self) -> Text:
        text = Text()
        for r in range(self.rows):
            for c in range(self.cols):
                bits = self.bits[r][c]
                text.append(chr(0x2800 + bits) if bits else " ", style=self.colour[r][c] or "")
            if r < self.rows - 1:
                text.append("\n")
        return text


class Projection:
    """lon/lat -> canvas dots, fitting a box and keeping its proportions."""

    def __init__(self, bbox: tuple[float, float, float, float], canvas: Canvas):
        lon0, lat0, lon1, lat1 = bbox
        self.k = math.cos(math.radians((lat0 + lat1) / 2))
        w, h = (lon1 - lon0) * self.k, lat1 - lat0
        self.scale = min((canvas.width - 2) / w, (canvas.height - 2) / h)
        self.ox = (canvas.width - w * self.scale) / 2 - lon0 * self.k * self.scale
        self.oy = (canvas.height - h * self.scale) / 2 + lat1 * self.scale

    def __call__(self, lat: float, lon: float) -> tuple[float, float]:
        return lon * self.k * self.scale + self.ox, self.oy - lat * self.scale


@functools.cache
def france_outline(cache: Path | None = None) -> list[list[tuple[float, float]]]:
    """Mainland France and its islands as rings of (lat, lon), simplified for a terminal."""
    if cache is not None and cache.exists():
        return [[tuple(p) for p in ring] for ring in json.loads(cache.read_text(encoding="utf-8"))]
    import shapely

    from ..geo import mainland
    shape = shapely.simplify(mainland(), 0.02)
    polygons = list(shape.geoms) if hasattr(shape, "geoms") else [shape]
    rings = [[(lat, lon) for lon, lat in poly.exterior.coords] for poly in polygons if poly.area > 0.002]
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rings), encoding="utf-8")
    return rings


def journey_bbox(journey: Journey, margin: float = 0.25) -> tuple[float, float, float, float]:
    points = [p for leg in journey.legs for p in leg.path]
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    lat0, lat1, lon0, lon1 = min(lats), max(lats), min(lons), max(lons)
    span = max(lat1 - lat0, (lon1 - lon0) * math.cos(math.radians(lat0)), 0.02)
    pad = span * margin
    return lon0 - pad, lat0 - pad, lon1 + pad, lat1 + pad


def draw(cols: int, rows: int, journey: Journey | None, outline: list, zoom: bool,
         network: tuple[np.ndarray, np.ndarray] | None = None) -> Text:
    """`network` is every place as (lats, lons): drawn faint, it shows where towns and lines are."""
    canvas = Canvas(cols, rows)
    bbox = journey_bbox(journey) if (journey is not None and zoom) else FRANCE_BBOX
    project = Projection(bbox, canvas)
    if network is not None:
        lats, lons = network
        canvas.scatter(lons * project.k * project.scale + project.ox, project.oy - lats * project.scale, NETWORK)
    for ring in outline:
        points = [project(lat, lon) for lat, lon in ring]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            canvas.line(x0, y0, x1, y1, OUTLINE)
    if journey is not None:
        ride = 0
        for leg in journey.legs:
            colour = WALK if leg.walk else RIDES[ride % len(RIDES)]
            ride += 0 if leg.walk else 1
            points = [project(lat, lon) for lat, lon in leg.path]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                canvas.line(x0, y0, x1, y1, colour)
        first, last = journey.legs[0].path, journey.legs[-1].path
        if first:
            canvas.disc(*project(*first[0]), START)
        if last:
            canvas.disc(*project(*last[-1]), END)
    return canvas.render()


def ride_colour(index: int) -> str:
    return RIDES[index % len(RIDES)]
