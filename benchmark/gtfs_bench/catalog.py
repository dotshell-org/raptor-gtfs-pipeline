"""Build and check the catalogue of French GTFS feeds.

    python -m gtfs_bench.catalog candidates   # catalog/candidates.csv, straight from the API
    python -m gtfs_bench.catalog check        # catalog/gtfs_france.csv against the API today

`candidates.csv` is generated and never edited: one row per GTFS resource published on
transport.data.gouv.fr (the PAN), with the facts needed to decide about it. `gtfs_france.csv`
is the curated catalogue the rest of the benchmark reads. It is edited by hand and carries
one row per decision, including the feeds left out and why, so `check` can tell a feed that
was refused from one nobody has looked at yet.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

PAN_DATASETS = "https://transport.data.gouv.fr/api/datasets"
GEO_DEPARTEMENTS = "https://geo.api.gouv.fr/departements?fields=code,nom,codeRegion"
GEO_EPCIS = "https://geo.api.gouv.fr/epcis?fields=code,codesRegions"
GEO_REGIONS = "https://geo.api.gouv.fr/regions"

#: Overseas regions (INSEE), plus "OM" for the overseas collectivities that belong to no
#: region (New Caledonia, French Polynesia…, communes 975xx-988xx). They run on other time
#: zones and connect to nothing on the mainland, so the benchmark leaves them out.
OVERSEAS_REGIONS = frozenset({"01", "02", "03", "04", "06", "OM"})

#: A feed whose service starts this far ahead is the next timetable, not the current one.
FUTURE_MARGIN = dt.timedelta(days=30)

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
CATALOG_DIR = BENCHMARK_DIR / "catalog"
CANDIDATES_CSV = CATALOG_DIR / "candidates.csv"
CATALOG_CSV = CATALOG_DIR / "gtfs_france.csv"

CANDIDATE_COLUMNS = [
    "region_code", "region_name", "status",
    "pan_dataset_id", "pan_slug", "dataset_title",
    "pan_resource_id", "resource_title",
    "publisher", "sub_types", "modes", "networks", "covered_area",
    "start_date", "end_date", "trips", "stop_points", "routes", "has_shapes",
    "licence", "updated", "url", "page_url",
]

#: Schema of the curated catalogue. Every other module reads feeds through these names.
CATALOG_COLUMNS = [
    "feed_id",          # unique slug, also the prefix every GTFS id of the feed gets
    "include",          # true / false
    "layer",            # regional | longue_distance
    "region_code",      # INSEE region code, or FR for a national feed
    "region_name",
    "metropole",        # one of METROPOLES, or empty
    "level",            # urbain | interurbain | agregat_regional | ferroviaire | national
    "name",
    "modes",
    "url",              # stable link to the latest version
    "auth",             # credentials key (see .env.example), or empty
    "keep_agencies",    # regex on agency_name: keep only these
    "drop_agencies",    # regex on agency_name: drop these (taken from another feed)
    "keep_stop_ids",    # regex on stop_id: keep only trips whose every stop matches
    "drop_stop_ids",    # regex on stop_id: drop trips with any stop matching
    "clip",             # true: keep only the part inside the tier's area
    "priority",         # lower wins when the same trip comes from two feeds
    "pan_dataset_id", "pan_resource_id",
    "licence", "stats_trips", "stats_stops", "valid_from", "valid_to",
    "notes",
]

#: The 22 legal métropoles: catalogue key -> (name, INSEE region).
METROPOLES = {
    "grand-paris": ("Métropole du Grand Paris", "11"),
    "lyon": ("Métropole de Lyon", "84"),
    "aix-marseille": ("Aix-Marseille-Provence", "93"),
    "lille": ("Métropole européenne de Lille", "32"),
    "bordeaux": ("Bordeaux Métropole", "75"),
    "toulouse": ("Toulouse Métropole", "76"),
    "nantes": ("Nantes Métropole", "52"),
    "nice": ("Métropole Nice Côte d'Azur", "93"),
    "strasbourg": ("Eurométropole de Strasbourg", "44"),
    "montpellier": ("Montpellier Méditerranée Métropole", "76"),
    "rennes": ("Rennes Métropole", "53"),
    "grenoble": ("Grenoble-Alpes Métropole", "84"),
    "rouen": ("Métropole Rouen Normandie", "28"),
    "toulon": ("Toulon Provence Méditerranée", "93"),
    "saint-etienne": ("Saint-Étienne Métropole", "84"),
    "tours": ("Tours Métropole Val de Loire", "24"),
    "orleans": ("Orléans Métropole", "24"),
    "dijon": ("Dijon Métropole", "27"),
    "metz": ("Metz Métropole", "44"),
    "nancy": ("Métropole du Grand Nancy", "44"),
    "clermont": ("Clermont Auvergne Métropole", "84"),
    "brest": ("Brest Métropole", "53"),
}


def _get_json(session: requests.Session, url: str, attempts: int = 3):
    # The PAN builds /api/datasets (about 2.5 MB) on the fly and is sometimes slow to start
    # sending it: give the read room, and try again before giving up.
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=(30, 300))
            response.raise_for_status()
            return response.json()
        except (requests.ConnectionError, requests.Timeout) as error:
            if attempt == attempts:
                raise
            wait = 10 * attempt
            print(f"{url}: {error.__class__.__name__}, retrying in {wait} s", file=sys.stderr)
            time.sleep(wait)


@dataclass
class RegionResolver:
    """Maps a PAN `covered_area` entry to INSEE region codes.

    The PAN states a region directly only for region-wide datasets. The rest name a commune
    (INSEE code), a département, or an EPCI by its SIREN, so each kind needs its own lookup.
    """

    region_names: dict[str, str]
    departement_region: dict[str, str]
    epci_regions: dict[str, list[str]]

    @classmethod
    def fetch(cls, session: requests.Session) -> RegionResolver:
        regions = _get_json(session, GEO_REGIONS)
        departements = _get_json(session, GEO_DEPARTEMENTS)
        epcis = _get_json(session, GEO_EPCIS)
        return cls(
            region_names={r["code"]: r["nom"] for r in regions},
            departement_region={d["code"]: d["codeRegion"] for d in departements},
            epci_regions={e["code"]: e.get("codesRegions") or [] for e in epcis},
        )

    def regions_of(self, area: dict) -> list[str]:
        kind, code = area.get("type"), str(area.get("insee") or "")
        if kind == "pays":
            # A national feed of France, or another country's (Monaco's buses are listed).
            return ["FR"] if code.upper() == "FR" else ["ETR"]
        if kind == "region":
            return [code]
        if kind == "departement":
            return [self.departement_region.get(code, "?")]
        if kind == "commune":
            if code.startswith("97") or code.startswith("98"):
                return [self.departement_region.get(code[:3], "OM")]
            return [self.departement_region.get(code[:2], "?")]
        if kind == "epci":
            return self.epci_regions.get(code) or ["?"]
        return ["?"]

    def name(self, code: str) -> str:
        special = {"FR": "National", "ETR": "Étranger", "OM": "Outre-mer"}
        return special.get(code) or self.region_names.get(code, "")


def candidate_status(dataset: dict, resource: dict, regions: list[str], today: dt.date) -> str:
    """Why a resource is or is not a candidate. Anything but `ok` is left out by default."""
    sub_types = set(dataset.get("sub_types") or [])
    if "zonal_drt" in sub_types:
        # Zonal on-demand service has no fixed stops or times, so it has nothing to route on.
        # Many datasets pair it with a fixed-route network, though, as two resources of one
        # dataset: only the on-demand resource goes.
        title = (resource.get("title") or "").lower()
        if sub_types == {"zonal_drt"} or any(w in title for w in ("tad", "zonal", "flex", "à la demande")):
            return "excluded:zonal_drt"
    if regions and all(code in OVERSEAS_REGIONS for code in regions):
        return "excluded:overseas"
    if regions and all(code == "ETR" for code in regions):
        return "excluded:foreign"
    if not resource.get("is_available", True):
        return "unavailable"
    metadata = resource.get("metadata")
    if not metadata:
        return "no_metadata"
    end = _date(metadata.get("end_date"))
    if end is not None and end < today:
        return "expired"
    start = _date(metadata.get("start_date"))
    if start is not None and start > today + FUTURE_MARGIN:
        return "future"
    return "ok"


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def build_candidates(datasets: list[dict], resolver: RegionResolver, today: dt.date) -> list[dict]:
    rows = []
    for dataset in datasets:
        if dataset.get("type") != "public-transit":
            continue
        areas = dataset.get("covered_area") or []
        regions = sorted({code for area in areas for code in resolver.regions_of(area)})
        for resource in dataset.get("resources") or []:
            # Community resources are third-party rewrites (Google Maps, Bus Tracker…), not
            # the producer's data. They also come without validation metadata.
            if resource.get("format") != "GTFS" or resource.get("community_resource_publisher"):
                continue
            metadata = resource.get("metadata") or {}
            stats = metadata.get("stats") or {}
            region_code = regions[0] if len(regions) == 1 else "|".join(regions)
            rows.append({
                "region_code": region_code,
                "region_name": "|".join(resolver.name(code) for code in regions),
                "status": candidate_status(dataset, resource, regions, today),
                "pan_dataset_id": dataset.get("datagouv_id") or dataset.get("id"),
                "pan_slug": dataset.get("slug"),
                "dataset_title": dataset.get("title"),
                "pan_resource_id": resource.get("id"),
                "resource_title": resource.get("title"),
                "publisher": (dataset.get("publisher") or {}).get("name"),
                "sub_types": "|".join(dataset.get("sub_types") or []),
                "modes": "|".join(metadata.get("modes") or resource.get("modes") or []),
                "networks": "|".join(metadata.get("networks") or []),
                "covered_area": "|".join(f"{a.get('type')}:{a.get('nom')}" for a in areas),
                "start_date": metadata.get("start_date"),
                "end_date": metadata.get("end_date"),
                "trips": stats.get("trips_count"),
                "stop_points": stats.get("stop_points_count", stats.get("stops_count")),
                "routes": stats.get("routes_count"),
                "has_shapes": metadata.get("has_shapes"),
                "licence": dataset.get("licence"),
                "updated": resource.get("updated"),
                "url": resource.get("url"),
                "page_url": resource.get("page_url"),
            })
    rows.sort(key=lambda r: (r["region_code"], r["dataset_title"] or "", str(r["pan_resource_id"])))
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_catalog(path: Path = CATALOG_CSV) -> list[dict]:
    """The curated catalogue, one dict per row, with `include` and `clip` as booleans."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for flag in ("include", "clip"):
            row[flag] = row.get(flag, "").strip().lower() == "true"
    return rows


def check_catalog(catalog: list[dict], candidates: list[dict]) -> list[str]:
    """Problems with the curated catalogue against the PAN as it is today."""
    problems = []
    by_resource = {str(c["pan_resource_id"]): c for c in candidates}
    seen = set()
    feed_ids = set()
    for row in catalog:
        feed_id = row["feed_id"]
        if feed_id in feed_ids:
            problems.append(f"{feed_id}: duplicate feed_id")
        feed_ids.add(feed_id)
        if row["metropole"] and row["metropole"] not in METROPOLES:
            problems.append(f"{feed_id}: unknown metropole {row['metropole']!r}")
        resource_id = row.get("pan_resource_id", "").strip()
        if not resource_id:
            continue  # not on the PAN (e.g. Data Grand Lyon)
        seen.add(resource_id)
        candidate = by_resource.get(resource_id)
        if candidate is None:
            if row["include"]:
                problems.append(f"{feed_id}: resource {resource_id} is no longer on the PAN")
            continue
        if row["include"] and candidate["status"] != "ok":
            problems.append(f"{feed_id}: included but now {candidate['status']}")
        if row["include"] and row["url"] != candidate["url"]:
            problems.append(f"{feed_id}: url changed to {candidate['url']}")
    for candidate in candidates:
        if candidate["status"] == "ok" and str(candidate["pan_resource_id"]) not in seen:
            problems.append(
                f"new candidate not in the catalogue: {candidate['pan_resource_id']} "
                f"{candidate['dataset_title']!r} ({candidate['region_name']})"
            )
    return problems


def fetch_candidates(today: dt.date | None = None) -> list[dict]:
    with requests.Session() as session:
        session.headers["User-Agent"] = "raptor-gtfs-pipeline-benchmark"
        resolver = RegionResolver.fetch(session)
        datasets = _get_json(session, PAN_DATASETS)
    return build_candidates(datasets, resolver, today or dt.date.today())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gtfs_bench.catalog", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["candidates", "check"])
    args = parser.parse_args(argv)

    candidates = fetch_candidates()
    if args.command == "candidates":
        write_csv(CANDIDATES_CSV, CANDIDATE_COLUMNS, candidates)
        ok = sum(1 for c in candidates if c["status"] == "ok")
        print(f"{len(candidates)} GTFS resources, {ok} ok -> {CANDIDATES_CSV}")
        return 0

    problems = check_catalog(read_catalog(), candidates)
    for problem in problems:
        print(problem)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
