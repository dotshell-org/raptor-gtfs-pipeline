"""The build's settings, in one place: settings.json beside this package.

Every value has a default here; settings.json (git-ignored: it is this machine's) holds only
what was changed. An explicit argument always wins. met-dataset-server carries the same values
in its config/france-live/settings.yaml.

    from gtfs_bench.settings import load
    s = load()
    s.merge.name_radius_m
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import typing
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import BENCHMARK_DIR

SETTINGS_FILE = BENCHMARK_DIR / "settings.json"


def _meta(label: str, help: str = "", choices: tuple = ()) -> dict:
    return {"label": label, "help": help, "choices": choices}


@dataclass
class Data:
    reference_date: str = field(default="", metadata=_meta(
        "Jour de référence (AAAA-MM-JJ)", "Vide : le mardi hors vacances où roulent le plus de flux"))
    coverage_days: int = field(default=42, metadata=_meta(
        "Jours examinés pour le choisir", "À partir d'aujourd'hui"))
    download_workers: int = field(default=6, metadata=_meta("Téléchargements en parallèle"))


@dataclass
class Merge:
    name_radius_m: float = field(default=500.0, metadata=_meta(
        "Rayon des homonymes (m)", "Arrêts de même nom plus proches que ça : un seul lieu"))
    transfer_radius_m: float = field(default=300.0, metadata=_meta("Rayon des correspondances à pied (m)"))
    transfer_max_neighbors: int = field(default=30, metadata=_meta("Voisins max par arrêt"))
    walk_speed_mps: float = field(default=1.33, metadata=_meta("Vitesse de marche (m/s)"))
    transfer_floor_s: int = field(default=60, metadata=_meta("Correspondance minimale (s)"))
    station_radius_m: float = field(default=500.0, metadata=_meta(
        "Rayon autour des gares (m)", "Liens élargis autour des arrêts des réseaux nationaux"))
    station_max_neighbors: int = field(default=60, metadata=_meta("Voisins max autour des gares"))
    duckdb_memory: str = field(default="6GB", metadata=_meta("Mémoire de DuckDB"))

    def transfer_params(self):
        from .transfers import TransferParams
        return TransferParams(radius_m=self.transfer_radius_m, max_neighbors=self.transfer_max_neighbors,
                              walk_speed_mps=self.walk_speed_mps, floor_s=self.transfer_floor_s)

    def station_params(self):
        from .transfers import StationParams
        return StationParams(radius_m=self.station_radius_m, max_neighbors=self.station_max_neighbors)


@dataclass
class Engine:
    pipeline_xmx: str = field(default="12g", metadata=_meta("Tas du pipeline", "Conversion de la France : ~10 Go"))


@dataclass
class Live:
    max_feed_share: float = field(default=0.005, metadata=_meta(
        "Part max d'un flux qui s'arrête avant la fin", "0,005 = 0,5 % des courses"))
    max_lost_share: float = field(default=0.01, metadata=_meta(
        "Part max perdue au total", "Petits flux arrêtés en route, cumulés"))
    horizon_days: int = field(default=300, metadata=_meta("Jours examinés en avant"))
    soon_days: int = field(default=35, metadata=_meta(
        "Flux « bientôt arrêtés » (jours)", "Pour chercher une version plus récente sur le PAN"))
    refresh_time: str = field(default="04:00", metadata=_meta("Heure de la mise à jour quotidienne"))


@dataclass
class School:
    few_runs: int = field(default=6, metadata=_meta(
        "Courses max d'une ligne scolaire « devinée »", "Ligne qui dessert un établissement et roule peu"))


@dataclass
class Settings:
    data: Data = field(default_factory=Data)
    merge: Merge = field(default_factory=Merge)
    engine: Engine = field(default_factory=Engine)
    live: Live = field(default_factory=Live)
    school: School = field(default_factory=School)

    def reference_date(self) -> dt.date | None:
        return dt.date.fromisoformat(self.data.reference_date) if self.data.reference_date.strip() else None


GROUPS = {"data": "Données", "merge": "Fusion des flux", "engine": "Pipeline",
          "live": "Réseau à jour (fenêtre glissante)", "school": "Lignes scolaires"}


def fields_of(settings: Settings):
    """(group key, group label, field name, label, help, type, value) for every setting."""
    for group in dataclasses.fields(settings):
        section = getattr(settings, group.name)
        hints = typing.get_type_hints(type(section))
        for f in dataclasses.fields(section):
            yield (group.name, GROUPS[group.name], f.name, f.metadata.get("label", f.name), f.metadata.get("help", ""),
                   hints[f.name], getattr(section, f.name))


def parse(kind, text: str):
    """A typed value from the text of a form field; ValueError when it does not read."""
    text = text.strip()
    if kind is bool:
        if text.lower() in ("true", "oui", "1", "vrai"):
            return True
        if text.lower() in ("false", "non", "0", "faux"):
            return False
        raise ValueError(f"oui ou non, pas {text!r}")
    if kind is int:
        return int(text)
    if kind is float:
        return float(text.replace(",", "."))
    return text


def load(path: Path = SETTINGS_FILE) -> Settings:
    settings = Settings()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            stored = {}
        for group, values in stored.items():
            section = getattr(settings, group, None)
            if section is None or not isinstance(values, dict):
                continue
            for name, value in values.items():
                if hasattr(section, name):
                    setattr(section, name, value)
    return settings


def save(settings: Settings, path: Path = SETTINGS_FILE) -> Path:
    """Only the values that differ from the defaults: a later default change still applies."""
    defaults = Settings()
    changed: dict[str, dict] = {}
    for group in dataclasses.fields(settings):
        for f in dataclasses.fields(getattr(settings, group.name)):
            value = getattr(getattr(settings, group.name), f.name)
            if value != getattr(getattr(defaults, group.name), f.name):
                changed.setdefault(group.name, {})[f.name] = value
    path.write_text(json.dumps(changed, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
