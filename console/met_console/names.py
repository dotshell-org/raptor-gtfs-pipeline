"""Search keys for stop and commune names."""

from __future__ import annotations

import re
import unicodedata


def name_key(name: str) -> str:
    """Case, accent and punctuation insensitive key: 'Gare SNCF' and 'GARE S.N.C.F.' match."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[.'`]", "", text)  # S.N.C.F. -> sncf, l'Eglise -> leglise
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def short_commune(name: str) -> str:
    """'Lyon 2e Arrondissement' -> 'Lyon 2e'."""
    return re.sub(r"\s+Arrondissement$", "", name)
