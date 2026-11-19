"""A map of France in braille: the outline, the network, and the journey drawn over it.

Each terminal cell holds a braille character, a 2 × 4 grid of dots, so a 60 × 20 cell map
is 120 × 80 dots. Braille dots are close to square on most fonts, which keeps France's
proportions with nothing more than the cos(latitude) factor. A cell has one colour: when
two layers meet, the more important one wins (endpoints, then rides, then walks, then the
outline, then the network).

On top of the dots, text: the big cities when the whole country shows, the start, the end
and the stops where one changes when the map follows a trip, and a scale bar. The view can
be moved: MapView takes + and − to zoom, the arrows to pan, 0 to go back to the trip, f for
the whole of France.
"""

from __future__ import annotations

import functools
import json
import math
from pathlib import Path

import numpy as np
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from .backend import Journey

# Dot (x, y) in the 2 × 4 cell -> bit of the braille character (U+2800 + bits).
_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
NETWORK = "#3b3a37"
NETWORK_DENSE = "#5b5a55"
OUTLINE = "#6b6a66"
WALK = "#c3c2b7"
START = "#1baf7a"
END = "#e34948"
CITY = "#9a998f"
#: Ride colours, in the data-viz palette's categorical order.
RIDES = ("#2a78d6", "#eb6834", "#eda100", "#e87ba4", "#6250d6", "#1baf7a", "#008300", "#e34948")
_PRIORITY = {NETWORK: -2, NETWORK_DENSE: -1, OUTLINE: 0, WALK: 1, START: 3, END: 3, **{c: 2 for c in RIDES}}
_BIT_TABLE = np.array(_BITS)

FRANCE_BBOX = (-5.3, 41.2, 9.7, 51.2)  # lon_min, lat_min, lon_max, lat_max

#: Cities named on the wide view, biggest first (a label that would overlap one already drawn
#: is skipped, so the order is the priority).
CITIES = (
    ("Paris", 48.857, 2.352), ("Marseille", 43.296, 5.370), ("Lyon", 45.764, 4.836), ("Toulouse", 43.605, 1.444),
    ("Nice", 43.710, 7.262), ("Nantes", 47.218, -1.554), ("Strasbourg", 48.573, 7.752), ("Montpellier", 43.611, 3.877),
    ("Bordeaux", 44.838, -0.579), ("Lille", 50.629, 3.057), ("Rennes", 48.117, -1.678), ("Reims", 49.258, 4.032),
    ("Toulon", 43.125, 5.931), ("Grenoble", 45.188, 5.725), ("Dijon", 47.322, 5.041), ("Brest", 48.390, -4.486),
    ("Clermont-Fd", 45.778, 3.087), ("Tours", 47.394, 0.685), ("Limoges", 45.834, 1.262), ("Rouen", 49.443, 1.100),
    ("Caen", 49.183, -0.370), ("Metz", 49.120, 6.176), ("Besançon", 47.238, 6.024), ("Orléans", 47.903, 1.909),
    ("Perpignan", 42.699, 2.895), ("Bayonne", 43.493, -1.475), ("Poitiers", 46.580, 0.340), ("Ajaccio", 41.919, 8.739),
    ("Bastia", 42.697, 9.451), ("La Rochelle", 46.160, -1.151), ("Amiens", 49.894, 2.296), ("Nancy", 48.692, 6.184),
    ("Le Mans", 48.006, 0.199), ("Avignon", 43.949, 4.806), ("Pau", 43.295, -0.370), ("Mulhouse", 47.750, 7.336),
    ("Annecy", 45.899, 6.129), ("Chambéry", 45.564, 5.918), ("Nîmes", 43.837, 4.360), ("Angers", 47.478, -0.563),
)


class Canvas:
    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = max(cols, 4), max(rows, 2)
        self.width, self.height = self.cols * 2, self.rows * 4
        self.bits = [[0] * self.cols for _ in range(self.rows)]
        self.colour: list[list[str | None]] = [[None] * self.cols for _ in range(self.rows)]
        self.overlay: dict[tuple[int, int], tuple[str, str]] = {}  # (row, col) -> (character, style)

    def dot(self, x: int, y: int, colour: str) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        row, col = y // 4, x // 2
        self.bits[row][col] |= _BITS[y % 4][x % 2]
        current = self.colour[row][col]
        if current is None or _PRIORITY.get(colour, 0) >= _PRIORITY.get(current, 0):
            self.colour[row][col] = colour

    def line(self, x0: float, y0: float, x1: float, y1: float, colour: str, dashed: bool = False) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            if dashed and (i // 2) % 2:
                continue
            t = i / steps
            self.dot(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), colour)

    def scatter(self, xs: np.ndarray, ys: np.ndarray, colour: str, dense_colour: str | None = None,
                dense_from: int = 4) -> None:
        """Many single dots at once (every stop of a network), without a Python loop per dot.
        Cells holding `dense_from` stops or more get `dense_colour`: towns stand out."""
        xs, ys = np.round(xs).astype(int), np.round(ys).astype(int)
        keep = (xs >= 0) & (xs < self.width) & (ys >= 0) & (ys < self.height)
        xs, ys = xs[keep], ys[keep]
        grid = np.zeros((self.rows, self.cols), dtype=np.int64)
        np.bitwise_or.at(grid, (ys // 4, xs % self.width // 2), _BIT_TABLE[ys % 4, xs % 2])
        counts = np.zeros((self.rows, self.cols), dtype=np.int64)
        np.add.at(counts, (ys // 4, xs % self.width // 2), 1)
        for row, col in zip(*np.nonzero(grid)):
            self.bits[row][col] |= int(grid[row, col])
            if self.colour[row][col] is None:
                dense = dense_colour is not None and counts[row, col] >= dense_from
                self.colour[row][col] = dense_colour if dense else colour

    def disc(self, x: float, y: float, colour: str) -> None:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.dot(round(x) + dx, round(y) + dy, colour)

    def label(self, x: float, y: float, text: str, style: str, side: str = "right") -> bool:
        """Text next to a dot, if it fits and overlaps no other label; True when drawn."""
        row = int(y) // 4
        col = int(x) // 2
        start = col + 2 if side == "right" else col - len(text) - 1
        if side == "right" and start + len(text) > self.cols:
            start = col - len(text) - 1
        if not (0 <= row < self.rows) or start < 0 or start + len(text) > self.cols:
            return False
        cells = [(row, start + i) for i in range(len(text))]
        margin = [(row, start - 1), (row, start + len(text))]
        if any(c in self.overlay for c in cells + margin):
            return False
        for (r, c), ch in zip(cells, text):
            self.overlay[(r, c)] = (ch, style)
        return True

    def text_at(self, row: int, col: int, text: str, style: str) -> None:
        for i, ch in enumerate(text):
            if 0 <= row < self.rows and 0 <= col + i < self.cols:
                self.overlay[(row, col + i)] = (ch, style)

    def render(self) -> Text:
        text = Text()
        for r in range(self.rows):
            for c in range(self.cols):
                if (r, c) in self.overlay:
                    ch, style = self.overlay[(r, c)]
                    text.append(ch, style=style)
                    continue
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
        w, h = max((lon1 - lon0) * self.k, 1e-6), max(lat1 - lat0, 1e-6)
        self.scale = min((canvas.width - 2) / w, (canvas.height - 2) / h)
        self.ox = (canvas.width - w * self.scale) / 2 - lon0 * self.k * self.scale
        self.oy = (canvas.height - h * self.scale) / 2 + lat1 * self.scale

    def __call__(self, lat: float, lon: float) -> tuple[float, float]:
        return lon * self.k * self.scale + self.ox, self.oy - lat * self.scale

    def km_per_dot(self) -> float:
        return 111.32 / self.scale


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


def scale_bar(project: Projection, cols: int) -> str:
    """A bar of a round length, about a sixth of the map's width: "├────┤ 20 km"."""
    km_per_cell = project.km_per_dot() * 2
    target = km_per_cell * max(cols // 6, 4)
    nice = min((n for n in (0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500) if n >= target * 0.6), default=500)
    cells = max(2, round(nice / km_per_cell))
    length = f"{nice:g} km".replace(".", ",")
    return "├" + "─" * (cells - 2) + "┤ " + length


def draw(cols: int, rows: int, journey: Journey | None, outline: list, zoom: bool,
         network: tuple[np.ndarray, np.ndarray] | None = None, bbox: tuple[float, float, float, float] | None = None,
         labels: bool = True) -> Text:
    """`network` is every place as (lats, lons): drawn faint, it shows where towns and lines are.
    `bbox` overrides the view (MapView's zoom and pan); otherwise the trip, or France."""
    canvas = Canvas(cols, rows)
    if bbox is None:
        bbox = journey_bbox(journey) if (journey is not None and zoom) else FRANCE_BBOX
    project = Projection(bbox, canvas)
    if network is not None:
        lats, lons = network
        canvas.scatter(lons * project.k * project.scale + project.ox, project.oy - lats * project.scale, NETWORK,
                       NETWORK_DENSE)
    for ring in outline:
        points = [project(lat, lon) for lat, lon in ring]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            canvas.line(x0, y0, x1, y1, OUTLINE)
    wide = (bbox[2] - bbox[0]) > 3.0
    if journey is not None:
        ride = 0
        for leg in journey.legs:
            colour = WALK if leg.walk else RIDES[ride % len(RIDES)]
            ride += 0 if leg.walk else 1
            points = [project(lat, lon) for lat, lon in leg.path]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                canvas.line(x0, y0, x1, y1, colour, dashed=leg.walk)
        first, last = journey.legs[0].path, journey.legs[-1].path
        if first:
            canvas.disc(*project(*first[0]), START)
        if last:
            canvas.disc(*project(*last[-1]), END)
        if labels:
            if first:
                canvas.label(*project(*first[0]), _short(journey.legs[0].from_name), f"bold {START}")
            if last:
                canvas.label(*project(*last[-1]), _short(journey.legs[-1].to_name), f"bold {END}")
            if not wide:  # the stops where one changes, when there is room to read them
                ride = 0
                for leg in journey.legs[:-1]:
                    ride += 0 if leg.walk else 1
                    if not leg.walk and leg.path:
                        canvas.label(*project(*leg.path[-1]), _short(leg.to_name, 18), RIDES[(ride - 1) % len(RIDES)])
    if labels and wide:
        for name, lat, lon in CITIES:
            x, y = project(lat, lon)
            if 0 <= x < canvas.width and 0 <= y < canvas.height:
                canvas.label(x, y, name, CITY)
    if labels:
        canvas.text_at(canvas.rows - 1, 1, scale_bar(project, canvas.cols), OUTLINE)
    return canvas.render()


def _short(name: str, width: int = 24) -> str:
    return name if len(name) <= width else name[: width - 1] + "…"


def ride_colour(index: int) -> str:
    return RIDES[index % len(RIDES)]


def legend(journey: Journey | None, zoom_note: str = "") -> Text:
    """One line under the map: each ride's colour and line, walks, start and end, the keys."""
    text = Text()
    if journey is not None:
        ride = 0
        for leg in journey.legs:
            if leg.walk:
                continue
            text.append("━━ ", style=RIDES[ride % len(RIDES)])
            text.append(f"{leg.route or '?'}  ", style="bold")
            ride += 1
        text.append("┄┄ ", style=WALK)
        text.append("à pied  ")
        text.append("● ", style=START)
        text.append("départ  ")
        text.append("● ", style=END)
        text.append("arrivée  ")
    text.append(f"{zoom_note}clic sur la carte puis + − ← → ↑ ↓, 0 : le trajet, f : la France", style="dim")
    return text


class MapView(Static, can_focus=True):
    """The map widget: the app gives it what to draw, it keeps its own zoom and pan."""

    BINDINGS = [
        Binding("plus,equals_sign", "zoom(0.5)", "Zoom +", show=False),
        Binding("minus", "zoom(2)", "Zoom −", show=False),
        Binding("left", "pan(-0.25, 0)", show=False),
        Binding("right", "pan(0.25, 0)", show=False),
        Binding("up", "pan(0, 0.25)", show=False),
        Binding("down", "pan(0, -0.25)", show=False),
        Binding("0", "reset", show=False),
        Binding("f", "france", show=False),
    ]
    DEFAULT_CSS = """
    MapView:focus { border: round $accent; }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.view: tuple[float, float, float, float] | None = None  # None: follow the app (trip or France)
        self.scene: dict = {}

    def show(self, journey, outline, zoom, network) -> None:
        self.scene = {"journey": journey, "outline": outline, "zoom": zoom, "network": network}
        self.redraw()

    def follow(self) -> None:
        """A new trip: the view goes back to following it."""
        self.view = None

    def current_bbox(self) -> tuple[float, float, float, float]:
        if self.view is not None:
            return self.view
        journey = self.scene.get("journey")
        return journey_bbox(journey) if journey is not None and self.scene.get("zoom") else FRANCE_BBOX

    def redraw(self) -> None:
        if not self.scene:
            return
        cols, rows = max(self.size.width, 20), max(self.size.height, 8)
        self.update(draw(cols, rows, self.scene["journey"], self.scene["outline"], self.scene["zoom"],
                         self.scene["network"], bbox=self.view))

    def on_resize(self) -> None:
        self.redraw()

    def on_click(self) -> None:
        self.focus()

    def action_zoom(self, factor: float) -> None:
        lon0, lat0, lon1, lat1 = self.current_bbox()
        cx, cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2
        hw, hh = (lon1 - lon0) / 2 * factor, (lat1 - lat0) / 2 * factor
        hw, hh = min(max(hw, 0.004), 12.0), min(max(hh, 0.003), 8.0)
        self.view = (cx - hw, cy - hh, cx + hw, cy + hh)
        self.redraw()

    def action_pan(self, dx: float, dy: float) -> None:
        lon0, lat0, lon1, lat1 = self.current_bbox()
        w, h = lon1 - lon0, lat1 - lat0
        self.view = (lon0 + dx * w, lat0 + dy * h, lon1 + dx * w, lat1 + dy * h)
        self.redraw()

    def action_reset(self) -> None:
        self.view = None
        self.redraw()

    def action_france(self) -> None:
        self.view = FRANCE_BBOX
        self.redraw()
