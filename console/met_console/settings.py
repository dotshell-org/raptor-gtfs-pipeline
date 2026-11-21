"""The console's settings: <data>/settings.json, edited in the Paramètres tab.

Every value has a default here; the file (per machine, git-ignored) holds only what was changed.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass, field
from pathlib import Path


def _meta(label: str, help: str = "") -> dict:
    return {"label": label, "help": help}


@dataclass
class Server:
    base_url: str = field(default="https://api.dotshell.eu", metadata=_meta(
        "Adresse du serveur", "La livraison officielle de france-live"))
    epoch: str = field(default="epoch-2-3", metadata=_meta("Format des données (epoch)", "Celui que lit raptor-kmp 2.4"))
    check_on_start: bool = field(default=True, metadata=_meta(
        "Vérifier au démarrage", "Regarde s'il y a une nouvelle version, sans l'installer"))


@dataclass
class Engine:
    xmx: str = field(default="1g", metadata=_meta(
        "Tas du moteur", "La France tient en 256m ; 99 correspondances demandent ~1,2g"))
    java: str = field(default="", metadata=_meta("Java", "Vide : JAVA_HOME, puis le PATH"))


@dataclass
class Routing:
    default_changes: int = field(default=4, metadata=_meta("Correspondances max par défaut"))
    geocoding: bool = field(default=True, metadata=_meta(
        "Recherche d'adresses (Photon)", "Le texte tapé part à photon.komoot.io"))
    fallback_walk_m: float = field(default=6000.0, metadata=_meta(
        "Marche élargie si rien à 500 m (m)", "0 : pas de second essai"))


@dataclass
class Settings:
    server: Server = field(default_factory=Server)
    engine: Engine = field(default_factory=Engine)
    routing: Routing = field(default_factory=Routing)


GROUPS = {"server": "Livraison", "engine": "Moteur", "routing": "Itinéraire"}


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


def check(settings: Settings) -> list[str]:
    """What is wrong with the values: they would break the engine or the updates."""
    problems = []
    if not settings.server.base_url.startswith(("https://", "http://")):
        problems.append("l'adresse du serveur commence par https://")
    if not settings.server.epoch.startswith("epoch-"):
        problems.append("l'epoch s'écrit epoch-2-3")
    xmx = settings.engine.xmx.strip().lower()
    if not (xmx[:-1].isdigit() and xmx[-1:] in ("m", "g")):
        problems.append("le tas s'écrit 512m, 1g, 2g…")
    if not 0 <= settings.routing.default_changes <= 99:
        problems.append("correspondances : de 0 à 99")
    return problems


def load(path: Path) -> Settings:
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


def save(settings: Settings, path: Path) -> Path:
    """Only the values that differ from the defaults: a later default change still applies."""
    defaults = Settings()
    changed: dict[str, dict] = {}
    for group in dataclasses.fields(settings):
        for f in dataclasses.fields(getattr(settings, group.name)):
            value = getattr(getattr(settings, group.name), f.name)
            if value != getattr(getattr(defaults, group.name), f.name):
                changed.setdefault(group.name, {})[f.name] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(changed, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
