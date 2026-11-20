"""What the console's "Actions" tab can run: every step of the notebook and the maintenance jobs.

Each task is a command line of the benchmark's own modules, run in a subprocess with the
venv's Python, so it does exactly what running it by hand does, and its output streams into
the console. Options are plain text, editable before each run.
"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from ..catalog import BENCHMARK_DIR

TASK_NAME = "raptor-gtfs-refresh"


@dataclass(frozen=True)
class Task:
    key: str
    title: str
    group: str
    what: str                       # one paragraph, shown before running
    module: str                     # python -m <module>, or "powershell:" for a script
    options: str = ""               # default options, editable
    duration: str = ""              # order of magnitude, shown to the user
    heavy: bool = False             # needs several GB of RAM: say so

    def command(self, options: str) -> list[str]:
        args = shlex.split(options, posix=True)
        if self.module.startswith("powershell:"):
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    self.module.removeprefix("powershell:") + (" " + options if options else "")]
        return [sys.executable, "-u", "-m", self.module, *args]


def schedule_command(time: str) -> str:
    script = BENCHMARK_DIR / "refresh.ps1"
    return (f"$a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass "
            f"-File \"{script}\"'; Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a "
            f"-Trigger (New-ScheduledTaskTrigger -Daily -At {time}) "
            f"-Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) -Force | Select-Object TaskName, State")


TASKS: tuple[Task, ...] = (
    Task("refresh", "Mise à jour quotidienne", "Données à jour",
         "Télécharge les flux qui ont changé, cherche sur le PAN les nouvelles versions des flux qui "
         "s'arrêtent bientôt, recalcule la fenêtre et les jours types, et reconstruit le réseau "
         "france-live si un flux a changé. --force : reconstruire quoi qu'il arrive ; --no-build : "
         "seulement télécharger et faire le point.",
         "gtfs_bench.refresh", "", "1 min, ou ~10 min s'il reconstruit", heavy=True),
    Task("horizon", "Horizon des flux", "Données à jour",
         "Compte les courses de chaque flux jour par jour, calcule la fenêtre (jusqu'où tous les flux "
         "qui comptent publient) et les jours types. Écrit results/feed_horizon.csv, .png et horizon.json.",
         "gtfs_bench.horizon", "", "~1 min (cache)"),
    Task("schedule", "Planifier la mise à jour quotidienne", "Données à jour",
         "Crée (ou remplace) la tâche Windows « raptor-gtfs-refresh » qui lance refresh.ps1 chaque jour "
         "à l'heure des paramètres, et au réveil suivant si le PC dormait. Modifie la configuration de "
         "Windows : à lancer seulement si tu le veux.",
         "powershell:", "", "instantané"),
    Task("unschedule", "Retirer la tâche planifiée", "Données à jour",
         "Supprime la tâche Windows « raptor-gtfs-refresh ».",
         f"powershell:Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false; 'tâche retirée'", "", "instantané"),
    Task("download", "Télécharger les flux", "Chaîne du notebook",
         "Télécharge la dernière version de chaque flux inclus du catalogue (requêtes conditionnelles : "
         "un fichier inchangé n'est pas retéléchargé). --feeds a,b : seulement ceux-là ; --force : tout.",
         "gtfs_bench.download", "--layer all", "1 à 5 min"),
    Task("catalog-check", "Vérifier le catalogue sur le PAN", "Chaîne du notebook",
         "Compare le catalogue au PAN d'aujourd'hui : ressources disparues, URL changées, flux expirés, "
         "nouveaux candidats. candidates : régénère catalog/candidates.csv.",
         "gtfs_bench.catalog", "check", "~30 s"),
    Task("convert", "Convertir des paliers", "Chaîne du notebook",
         "Passe des paliers fusionnés (data/merged) dans le pipeline, avec la mesure du temps et de la "
         "mémoire. --tiers metropole:lyon,france ; sans --tiers : les 36 paliers (~45 min).",
         "gtfs_bench.convert", "--tiers metropole:lyon", "1 s à 45 min", heavy=True),
    Task("connected", "Construire les variantes France", "Chaîne du notebook",
         "France juxtaposée, une ligne par desserte, connexe, complète : fusion, pipeline, banc d'essai, "
         "audit de connexité, préfectures, lignes scolaires. --variants france-complete ; "
         "--skip-build : remesurer sans reconstruire.",
         "gtfs_bench.connected", "--variants france-complete", "~25 min par variante", heavy=True),
    Task("tiers", "Construire les métropoles et régions", "Données à jour",
         "Fusionne et convertit les 22 métropoles et 13 régions avec les jours types et la fenêtre de "
         "france-live, lignes scolaires comprises, sans banc d'essai ni résultats. "
         "--tiers metropole:lyon,region:84 : seulement ceux-là.",
         "gtfs_bench.tiers", "", "~30 min", heavy=True),
    Task("school", "Lignes scolaires des réseaux convertis", "Chaîne du notebook",
         "Repère les lignes scolaires, écrit school_routes.json à côté des .bin, vérifie la numérotation "
         "contre le moteur et mesure l'interrupteur.",
         "gtfs_bench.connected", "--school-only --variants france-connexe,france-complete", "~5 min"),
    Task("notebook", "Exécuter le notebook complet", "Chaîne du notebook",
         "Lance notebooks/gtfs_france.ipynb de bout en bout (téléchargement, fusion des 36 paliers, "
         "pipeline, moteur, variantes) et range la copie exécutée dans data/tmp/notebook.",
         "jupyter", "nbconvert --to notebook --execute notebooks/gtfs_france.ipynb --output-dir data/tmp/notebook "
         "--ExecutePreprocessor.timeout=-1", "1 h à 2 h", heavy=True),
    Task("engine", "Banc d'essai moteur", "Mesures",
         "Charge un palier converti dans raptor-kmp et mesure chargement, mémoire et temps de recherche "
         "(aléatoires, locales, scénarios). --tiers … ; --no-sweep : sans la recherche du tas minimal.",
         "gtfs_bench.engine", "--tiers metropole:lyon --no-sweep", "1 à 10 min"),
    Task("addresses", "Coût des recherches par adresse", "Mesures",
         "Les mêmes trajets demandés depuis l'arrêt le plus proche, les arrêts à 500 m et l'adresse. "
         "Écrit results/address_queries.csv.",
         "gtfs_bench.engine", "--addresses", "~10 min"),
    Task("engines", "Comparer deux versions de raptor-kmp", "Mesures",
         "Mêmes trajets (hachés), mémoire, temps, plus petit tas, jours types. Les versions doivent "
         "être installées (install 2.2.0 ; publish puis install 2.4.0-SNAPSHOT --local).",
         "gtfs_bench.engines", "compare 2.2.0 2.4.0-SNAPSHOT --networks metropole-lyon", "5 min à 1 h"),
    Task("tests", "Tests", "Maintenance",
         "La suite pytest du benchmark (catalogue, fusion, scolaire, horizon, explorateur…).",
         "pytest", "-q", "~30 s"),
    Task("guide", "Régénérer le guide PDF", "Maintenance",
         "Refait les captures de la console, le guide HTML et docs/guide-console.pdf (avec Edge).",
         "gtfs_bench.guide", "", "~1 min"),
)


def task(key: str) -> Task:
    return next(t for t in TASKS if t.key == key)


def environment() -> dict[str, str]:
    """The subprocess environment: UTF-8 output, and a JDK 21 if JAVA_HOME is not set."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if not env.get("JAVA_HOME"):
        jdks = sorted((Path.home() / ".gradle" / "jdks").glob("*21*"))
        if jdks:
            env["JAVA_HOME"] = str(jdks[-1])
    return env


def describe(command: list[str]) -> str:
    return " ".join(shlex.quote(part) if " " in part else part for part in command)
