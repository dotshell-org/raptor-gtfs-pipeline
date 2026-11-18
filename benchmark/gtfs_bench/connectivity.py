"""Is a merged France one network? Two answers, one per layer of the question.

1. **The graph** (`audit`): on the reference day, stops are nodes; a ride between two
   consecutive stops of a trip, or a transfer, is an edge. Connected components say
   whether the network is one piece, and the pieces left over ("islands") say where it
   breaks, with the distance to the main network as a hint of why:

   - a few hundred metres: a missing link (a station whose stops sit just out of reach);
   - a few kilometres: a network with no walkable link to the rest;
   - further: nothing reaches it on that day (an island, a valley, a feed of its own).

   Weak components ignore direction; strong ones need a way back. Both are upper bounds of
   what the engine can do: RAPTOR does not chain two walks, and a ride must leave after the
   traveller arrives.

2. **The engine** (`reachability`): from Paris at 07:00, raptor-kmp searches every
   préfecture of mainland France on the converted network, as a traveller would.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from . import geo
from .catalog import BENCHMARK_DIR
from .normalize import _sql_str, connect

TMP_DIR = BENCHMARK_DIR / "data" / "tmp"
PREFECTURES_CACHE = geo.GEO_DIR / "prefectures.json"
GEO_API = "https://geo.api.gouv.fr"
#: Paris, Châtelet: where the reachability searches leave from (stops within the radius).
PARIS = (48.8584, 2.3470)
ISLAND_CAUSES = ((500, "missing link"), (3000, "no walkable link"), (float("inf"), "no link at all"))


@dataclass
class Audit:
    network: str
    reference_date: str
    active_stops: int = 0           # stops served by a trip that day
    ride_edges: int = 0
    transfer_edges: int = 0
    weak_components: int = 0
    giant_weak_stops: int = 0
    giant_weak_share: float = 0.0
    strong_components: int = 0
    giant_strong_stops: int = 0
    giant_strong_share: float = 0.0
    islands_10_plus: int = 0        # weak components of 10 stops or more, the giant one aside
    stops_in_islands: int = 0
    islands: list = field(default_factory=list)

    def summary(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "islands"}


# ── the graph ────────────────────────────────────────────────────────────────────────


def _extract(zip_path: Path, names: tuple[str, ...], target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        for name in names:
            # The merge wrote these zips itself, flat: no path to sanitize beyond the name.
            with archive.open(name) as source, (target / name).open("wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)
    return target


def day_graph(zip_path: Path, day: dt.date, memory_limit: str = "6GB") -> tuple[pd.DataFrame, np.ndarray, np.ndarray, int]:
    """Stops served on `day`, and the edges between them (indices into the stops frame).

    Returns (stops, sources, targets, ride_edge_count). Read from the merged zip, so before
    the pipeline: what the pipeline then drops (see RESULTS.md) is not reflected here.
    """
    work = _extract(zip_path, ("stops.txt", "trips.txt", "calendar_dates.txt", "stop_times.txt", "transfers.txt"),
                    TMP_DIR / f"graph-{zip_path.stem}")
    con = connect(memory_limit)
    try:
        def csv(name: str) -> str:
            return (f"read_csv({_sql_str((work / name).as_posix())}, header = true, all_varchar = true, "
                    f"quote = '\"', escape = '\"', parallel = false)")
        con.execute(f"""CREATE TEMP TABLE day_trips AS SELECT trip_id FROM {csv('trips.txt')}
            WHERE service_id IN (SELECT service_id FROM {csv('calendar_dates.txt')} WHERE date = {_sql_str(day.strftime('%Y%m%d'))})""")
        con.execute(f"""CREATE TEMP TABLE rides AS SELECT DISTINCT a, b FROM (
                SELECT stop_id AS a, lead(stop_id) OVER (PARTITION BY trip_id ORDER BY CAST(stop_sequence AS INTEGER)) AS b
                FROM {csv('stop_times.txt')} WHERE trip_id IN (SELECT trip_id FROM day_trips))
            WHERE b IS NOT NULL AND a <> b""")
        con.execute(f"""CREATE TEMP TABLE active AS SELECT a AS stop_id FROM rides UNION SELECT b FROM rides""")
        stops = con.execute(f"""SELECT s.stop_id, s.stop_name, CAST(s.stop_lat AS DOUBLE) AS lat, CAST(s.stop_lon AS DOUBLE) AS lon,
                   split_part(s.stop_id, ':', 1) AS feed_id
            FROM {csv('stops.txt')} s JOIN active USING (stop_id) ORDER BY s.stop_id""").df()
        con.register("stop_index", pd.DataFrame({"stop_id": stops["stop_id"], "i": np.arange(len(stops))}))
        rides = con.execute("""SELECT fa.i, fb.i FROM rides r JOIN stop_index fa ON fa.stop_id = r.a
            JOIN stop_index fb ON fb.stop_id = r.b""").fetchnumpy()
        walks = con.execute(f"""SELECT fa.i, fb.i FROM {csv('transfers.txt')} t
            JOIN stop_index fa ON fa.stop_id = t.from_stop_id JOIN stop_index fb ON fb.stop_id = t.to_stop_id
            WHERE t.from_stop_id <> t.to_stop_id""").fetchnumpy()
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)
    ride_a, ride_b = list(rides.values())
    walk_a, walk_b = list(walks.values())
    sources = np.concatenate([ride_a, walk_a]).astype(np.int64)
    targets = np.concatenate([ride_b, walk_b]).astype(np.int64)
    return stops, sources, targets, len(ride_a)


def _region_names() -> dict[str, str]:
    from .catalog import read_catalog
    return {r["region_code"]: r["region_name"] for r in read_catalog() if r["region_code"] in geo.MAINLAND_REGIONS}


def audit(zip_path: Path, day: dt.date, network: str, memory_limit: str = "6GB", top: int = 40,
          graph=None) -> tuple[Audit, pd.DataFrame]:
    """Components of `zip_path` on `day`. Returns the audit and the stops with their component."""
    stops, sources, targets, rides = graph or day_graph(zip_path, day, memory_limit)
    n = len(stops)
    result = Audit(network, day.isoformat(), active_stops=n, ride_edges=rides, transfer_edges=len(sources) - rides)
    if not n:
        return result, stops
    matrix = coo_matrix((np.ones(len(sources), dtype=np.int8), (sources, targets)), shape=(n, n)).tocsr()
    result.weak_components, weak = connected_components(matrix, directed=True, connection="weak")
    result.strong_components, strong = connected_components(matrix, directed=True, connection="strong")
    weak_sizes, strong_sizes = np.bincount(weak), np.bincount(strong)
    giant = int(np.argmax(weak_sizes))
    result.giant_weak_stops, result.giant_strong_stops = int(weak_sizes.max()), int(strong_sizes.max())
    result.giant_weak_share = round(result.giant_weak_stops / n, 4)
    result.giant_strong_share = round(result.giant_strong_stops / n, 4)
    result.stops_in_islands = n - result.giant_weak_stops
    stops = stops.assign(component=weak, in_giant=weak == giant)

    # The islands, biggest first, with how far they lie from the main network.
    xy = geo.project(stops["lat"].to_numpy(), stops["lon"].to_numpy())
    main = np.flatnonzero(stops["in_giant"].to_numpy())
    tree = cKDTree(xy[main])
    distance, nearest = tree.query(xy)
    stops["to_main_m"] = np.where(stops["in_giant"], 0.0, distance)
    stops["nearest_main"] = stops["stop_name"].to_numpy()[main[nearest]]
    regions = geo.regions()
    names = _region_names()
    islands = []
    others = [c for c in np.argsort(-weak_sizes) if c != giant and weak_sizes[c] > 0]
    result.islands_10_plus = int(sum(weak_sizes[c] >= 10 for c in others))
    for c in others[:top]:
        members = stops[stops["component"] == c]
        closest = members.loc[members["to_main_m"].idxmin()]
        centre = shapely.Point(members["lon"].mean(), members["lat"].mean())
        region = next((code for code, shape in regions.items() if shape.contains(centre)), "")
        gap = float(closest["to_main_m"])
        islands.append({
            "network": network, "stops": len(members), "feed": members["feed_id"].mode().iat[0],
            "feeds": len(set(members["feed_id"])), "region": names.get(region, region),
            "example_stop": members["stop_name"].mode().iat[0], "lat": round(members["lat"].mean(), 4),
            "lon": round(members["lon"].mean(), 4), "gap_to_main_m": round(gap),
            "closest_stop": closest["stop_name"], "closest_main_stop": closest["nearest_main"],
            "likely_cause": next(label for limit, label in ISLAND_CAUSES if gap <= limit),
        })
    result.islands = islands
    return result, stops


def outlines(tolerance: float = 0.01) -> list[tuple[list[float], list[float]]]:
    """The mainland's coastline and borders as (lons, lats) rings, for maps."""
    shape = shapely.union_all(list(geo.regions().values())).simplify(tolerance)
    polygons = getattr(shape, "geoms", [shape])
    return [tuple(map(list, polygon.exterior.xy)) for polygon in polygons if polygon.area > 0.01]


# ── the engine: Paris → every préfecture ─────────────────────────────────────────────


def prefectures(cache: Path = PREFECTURES_CACHE) -> pd.DataFrame:
    """Every mainland département's préfecture, at its town hall (geo.api.gouv.fr, cached)."""
    if not cache.exists():
        with requests.Session() as session:
            session.headers["User-Agent"] = "raptor-gtfs-pipeline-benchmark"
            departments = session.get(f"{GEO_API}/departements", params={"fields": "nom,code,codeRegion,chefLieu"},
                                      timeout=60).json()
            rows = []
            for d in departments:
                if d["codeRegion"] not in geo.MAINLAND_REGIONS:
                    continue
                commune = session.get(f"{GEO_API}/communes/{d['chefLieu']}", params={"fields": "nom,centre,mairie"},
                                      timeout=60).json()
                point = (commune.get("mairie") or commune["centre"])["coordinates"]
                rows.append({"department": d["code"], "department_name": d["nom"], "region_code": d["codeRegion"],
                             "prefecture": commune["nom"], "insee": d["chefLieu"], "lat": point[1], "lon": point[0]})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return pd.DataFrame(json.loads(cache.read_text(encoding="utf-8")))


def reachability(server, network: str, departure: int = 7 * 3600, max_rounds: int = 8,
                 origin: tuple[float, float] = PARIS, origin_radius_m: float = 300.0,
                 destination_radius_m: float = 800.0, progress=print) -> pd.DataFrame:
    """Earliest arrival from Paris to every préfecture, by raptor-kmp on `server`'s network.

    A préfecture is every stop within `destination_radius_m` of its town hall (twice that if
    none is so close). `server` is a gtfs_bench.explorer.backend.EngineServer.
    """
    stops = pd.DataFrame(server.stops(), columns=["id", "name", "lat", "lon"])
    xy = geo.project(stops["lat"].to_numpy(), stops["lon"].to_numpy())
    tree = cKDTree(xy)

    def near(lat: float, lon: float, radius: float) -> list[int]:
        point = geo.project(np.array([lat]), np.array([lon]))[0]
        return stops["id"].iloc[tree.query_ball_point(point, radius)].tolist()

    origins = near(*origin, origin_radius_m)
    rows = []
    for p in prefectures().itertuples():
        if p.department == "75":
            continue
        targets = near(p.lat, p.lon, destination_radius_m) or near(p.lat, p.lon, 2 * destination_radius_m)
        row = {"network": network, "department": p.department, "prefecture": p.prefecture, "lat": p.lat, "lon": p.lon,
               "destination_stops": len(targets), "found": False, "arrival": None, "duration_min": None,
               "changes": None, "routes": "", "search_ms": None, "max_rounds": max_rounds}
        if targets and origins:
            result = server.route(origins, targets, departure, max_rounds=max_rounds)
            best = result.best()
            row["search_ms"] = round(result.ms, 2)
            if best is not None:
                row.update(found=True, arrival=f"{best.arrival // 3600:02d}:{best.arrival % 3600 // 60:02d}",
                           duration_min=round((best.arrival - departure) / 60), changes=best.changes,
                           routes=", ".join(leg.route or "?" for leg in best.rides))
        rows.append(row)
    frame = pd.DataFrame(rows)
    progress(f"{network}: {int(frame['found'].sum())}/{len(frame)} préfectures reached from Paris "
             f"(departure {departure // 3600:02d}:00, {max_rounds} rounds)")
    return frame
