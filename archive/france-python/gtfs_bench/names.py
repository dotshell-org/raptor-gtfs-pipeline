"""Make stop names unique per place, so the engine does not link distant homonyms.

raptor-kmp gives every pair of stops with exactly the same name a 120 s transfer
(Network.implicitTransferData). Inside one network that is how a station's platforms
are tied together. Across France it ties every "Mairie" to every other "Mairie": k stops
of one name make k·(k−1) transfers, most of them hundreds of kilometres long.

Stops sharing a name are grouped into places: two of them belong to the same place when
a chain of same-name stops, each within `radius_m` of the next, links them. A name
covering a single place is left alone. A name covering several places has each place
renamed with its commune, "Mairie (Vénissieux)", and with a number when one commune
holds two separate places of that name. The engine then links only stops of one place.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .geo import project


def name_key(name: str) -> str:
    """Case, accent and punctuation insensitive key: 'Gare SNCF' and 'GARE S.N.C.F.' match."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[.'`]", "", text)  # S.N.C.F. -> sncf, l'Eglise -> leglise
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def short_commune(name: str) -> str:
    """'Lyon 2e Arrondissement' -> 'Lyon 2e'."""
    return re.sub(r"\s+Arrondissement$", "", name)


def implicit_transfer_pairs(names: pd.Series) -> int:
    """Σ k·(k−1) over names, the way the engine counts them: exact string equality."""
    counts = names.value_counts()
    return int((counts * (counts - 1)).sum())


@dataclass
class NamesReport:
    stops: int
    homonym_names: int            # names (by key) carried by stops in more than one place
    renamed_stops: int
    largest_group_before: int     # most stops sharing one exact name, before
    largest_group_after: int
    implicit_pairs_before: int
    implicit_pairs_after: int


def disambiguate(stops: pd.DataFrame, commune_lookup: Callable, radius_m: float = 500.0) -> tuple[pd.Series, NamesReport]:
    """New names for `stops` (columns stop_id, stop_name, lat, lon), indexed like the input.

    `commune_lookup(lat_array, lon_array) -> list[str]` names the commune of each point.
    """
    names = stops["stop_name"].fillna("").astype(str).reset_index(drop=True)
    keys = names.map(name_key)
    new_names = names.copy()
    codes, _ = pd.factorize(keys)
    shared = np.flatnonzero((np.bincount(codes)[codes] >= 2) & (keys.to_numpy() != ""))
    homonym_count = 0

    if len(shared):
        # One pass for the whole country: neighbours within radius_m, kept only when they
        # bear the same name; the connected components of what is left are the places.
        lat, lon = stops["lat"].to_numpy()[shared], stops["lon"].to_numpy()[shared]
        pairs = cKDTree(project(lat, lon)).query_pairs(radius_m, output_type="ndarray")
        sub_codes = codes[shared]
        pairs = pairs[sub_codes[pairs[:, 0]] == sub_codes[pairs[:, 1]]] if len(pairs) else pairs
        n = len(shared)
        graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, place = connected_components(graph, directed=False)
        frame = pd.DataFrame({"row": shared, "code": sub_codes, "place": place, "lat": lat, "lon": lon})
        places_per_name = frame.groupby("code")["place"].nunique()
        homonyms = frame[frame["code"].isin(places_per_name.index[places_per_name > 1])]
        homonym_count = int((places_per_name > 1).sum())
        if len(homonyms):
            places = homonyms.groupby("place").agg(code=("code", "first"), size=("row", "size"),
                                                   lat=("lat", "mean"), lon=("lon", "mean"))
            places["commune"] = [short_commune(c) for c in commune_lookup(places["lat"].to_numpy(), places["lon"].to_numpy())]
            # Bigger places first, so the number goes to the smaller of two same-commune places.
            places = places.sort_values(["code", "commune", "size"], ascending=[True, True, False])
            rank = places.groupby(["code", "commune"]).cumcount() + 1
            places["label"] = np.where(rank == 1, places["commune"], places["commune"] + " " + rank.astype(str))
            suffix = homonyms["place"].map(places["label"])
            rows = homonyms["row"].to_numpy()
            new_names.iloc[rows] = (names.iloc[rows].to_numpy() + " (" + suffix.to_numpy() + ")")
    new_names.index = stops.index

    names.index = stops.index
    report = NamesReport(
        stops=len(stops),
        homonym_names=homonym_count,
        renamed_stops=int((new_names != names).sum()),
        largest_group_before=int(names.value_counts().max()) if len(names) else 0,
        largest_group_after=int(new_names.value_counts().max()) if len(names) else 0,
        implicit_pairs_before=implicit_transfer_pairs(names),
        implicit_pairs_after=implicit_transfer_pairs(new_names),
    )
    return new_names, report
