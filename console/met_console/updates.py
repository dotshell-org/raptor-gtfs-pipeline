"""The Mise à jour tab: what the server offers, an update as it happens, what it cost, and every
update so far.

The update itself is SyncKt (console/engine): dataset-sync, the library the apps use, checking
latest.json, taking the delta pack from the installed version when the server has one (else
the full pack), rebuilding the new version beside the old, checking every file's SHA-256, then
switching in one rename. This tab reads its JSON lines and draws them.
"""

from __future__ import annotations

import datetime as dt
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label, RichLog, Static

from . import history as history_module
from .dataset import Installed, megabytes
from .loading import SPINNER
from .sync import SyncRun

GREEN, RED, ORANGE, BLUE, PURPLE = "#1baf7a", "#e34948", "#eda100", "#2a78d6", "#6250d6"
#: Where a file's bytes came from: name, colour, what it means.
SOURCES = (("copied", GREEN, "copié de la version installée"), ("reused", BLUE, "repris dans la nouvelle version"),
           ("inserted", ORANGE, "téléchargé"), ("derived", PURPLE, "recalculé sur place"))
METHODS = {"delta": "par différence", "full": "paquet complet", "files": "fichier par fichier"}


def percent(part: float, whole: float) -> str:
    if not whole:
        return "–"
    value = part * 100 / whole
    text = f"{value:.1f}" if value < 10 else f"{value:.0f}"
    return text.replace(".", ",") + " %"


def duration_text(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s".replace(".", ",")


def share_bar(file: dict, width: int = 24) -> Text:
    """One file's bytes by where they came from, as a bar of `width` cells."""
    total = max(file.get("bytes") or 0, 1)
    text, used = Text(), 0
    for i, (key, colour, _) in enumerate(SOURCES):
        cells = round((file.get(key) or 0) * width / total)
        if i == len(SOURCES) - 1:
            cells = width - used if file.get(key) else min(cells, width - used)
        cells = max(0, min(cells, width - used))
        text.append("█" * cells, style=colour)
        used += cells
    text.append("░" * (width - used), style="dim")
    return text


def legend() -> Text:
    text = Text()
    for key, colour, label in SOURCES:
        text.append("█ ", style=colour)
        text.append(f"{label}   ", style="dim")
    return text


def progress_text(done: int, total: int, speed: float | None, frame: int, finished: bool = False,
                  resumed_from: int = 0, width: int = 48) -> Text:
    """The download bar: bytes so far, speed, and where a resumed download started."""
    fraction = min(done / total, 1.0) if total else 0.0
    filled = round(fraction * width)
    text = Text()
    resumed = round(min(resumed_from / total, 1.0) * width) if total else 0
    for i in range(width):
        if i < resumed:
            text.append("━", style="#8fb8ef")
        elif i < filled:
            text.append("━", style=GREEN if finished else BLUE)
        else:
            text.append("━", style="dim")
    text.append(f"  {megabytes(done)} / {megabytes(total)}  {fraction * 100:3.0f} %", style="bold")
    if speed:
        text.append(f"  ·  {megabytes(int(speed))}/s", style="dim")
    if resumed_from:
        text.append(f"  ·  repris à {megabytes(resumed_from)}", style="#8fb8ef")
    if not finished and fraction < 1:
        text.append(f"  {SPINNER[frame % len(SPINNER)]}", style=ORANGE)
    return text


def offers_text(latest: dict | None, installed: str | None) -> Text:
    """What the server can send: the full pack, and a delta from each version it keeps one for."""
    text = Text()
    if not latest:
        return text
    full, total = latest.get("full_bytes"), latest.get("total_bytes")
    text.append("Le serveur propose\n", style="bold")
    if full:
        text.append(f"  paquet complet       {megabytes(full):>10}   ({percent(full, total)} de la version)\n")
    deltas = latest.get("deltas") or {}
    for version, size in sorted(deltas.items(), reverse=True):
        mine = version == installed
        text.append(f"  depuis {version}  {megabytes(size):>10}   ({percent(size, full)} du complet)",
                    style=f"bold {GREEN}" if mine else "")
        text.append("  ← la vôtre\n" if mine else "\n", style=GREEN)
    if not deltas:
        text.append("  aucune différence : le serveur n'a pas encore d'autre version\n", style="dim")
    elif installed and installed != latest.get("version") and installed not in deltas:
        text.append("  rien depuis la vôtre, trop ancienne : ce sera le paquet complet\n", style=ORANGE)
    return text


def result_text(done: dict, plan: dict | None, seconds: float, files: int) -> Text:
    """What an update cost, against what the full pack and the version weigh."""
    plan = plan or {}
    downloaded, full, total = done.get("downloaded") or 0, plan.get("full_bytes"), plan.get("total_bytes")
    size = done.get("bytes") or total or 0
    text = Text()
    text.append(f"✓ {done.get('version')}", style=f"bold {GREEN}")
    text.append(f"  {METHODS.get(done.get('method'), done.get('method'))}"
                + (f" depuis {done['from']}" if done.get("from") else "") + "\n\n")
    text.append(f"{megabytes(downloaded)} téléchargés", style="bold")
    if full:
        text.append(f"  ·  {percent(downloaded, full)} du paquet complet ({megabytes(full)})")
    if total:
        text.append(f"  ·  {percent(downloaded, total)} de la version ({megabytes(total)})")
    text.append("\n")
    for key, colour, label in SOURCES:
        value = done.get(key) or 0
        if value:
            text.append("█ ", style=colour)
            text.append(f"{megabytes(value)} {label} ({percent(value, size)})\n")
    text.append(f"\n{files} fichiers reconstruits, chacun vérifié par SHA-256, puis basculés d'un coup.\n", style="dim")
    text.append(f"téléchargement {duration_text((done.get('download_ms') or 0) / 1000)}  ·  "
                f"écriture {duration_text((done.get('apply_ms') or 0) / 1000)}  ·  "
                f"en tout {duration_text(seconds)}", style="dim")
    return text


class UpdatePane(Vertical):
    """Check the server and install its latest version, with SyncKt (dataset-sync)."""

    DEFAULT_CSS = """
    UpdatePane { padding: 0 1; }
    UpdatePane #up-top { height: auto; max-height: 12; }
    UpdatePane #up-state { width: 1fr; height: auto; padding: 1 1; background: $boost; }
    UpdatePane #up-offers { width: 1fr; height: auto; padding: 1 1; margin-left: 1; background: $boost; }
    UpdatePane #up-bar { height: 3; margin-top: 1; }
    UpdatePane #up-bar Button { margin-right: 1; }
    UpdatePane #up-hint { padding: 1 1; color: $text-muted; width: 1fr; }
    UpdatePane #up-progress { height: 1; padding: 0 1; margin-top: 1; }
    UpdatePane #up-middle { height: 1fr; margin-top: 1; }
    UpdatePane #up-files { width: 1fr; }
    UpdatePane #up-result { width: 66; padding: 0 1; margin-left: 1; border-left: solid $panel-lighten-2; }
    UpdatePane #up-legend { height: 1; padding: 0 1; }
    UpdatePane .up-title { text-style: bold; color: $accent; margin-top: 1; }
    UpdatePane #up-history { height: 8; }
    UpdatePane #up-log { height: 5; border: round $panel-lighten-2; }
    """

    def __init__(self, runner=SyncRun, **kwargs):
        super().__init__(**kwargs)
        self.runner = runner
        self.running: SyncRun | None = None
        self.checking = False
        self.stopped = False
        self.latest: dict | None = None
        self.plan: dict | None = None
        self.messages: list[str] = []  # what the log says, in plain text
        self.frame = 0
        self._reset_run()

    def _reset_run(self) -> None:
        self.started = 0.0
        self.progress: tuple[int, int] | None = None      # (done, total)
        self.resumed_from = 0
        self.speed: float | None = None
        self._first: tuple[float, int] | None = None      # (time, bytes) of the first progress line
        self.files: list[dict] = []
        self.done: dict | None = None
        self.error: dict | None = None
        self.run_plan: dict | None = None

    # ── layout ───────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="up-top"):
            yield Static("", id="up-state")
            yield Static("", id="up-offers")
        with Horizontal(id="up-bar"):
            yield Button("Vérifier", id="up-check")
            yield Button("Mettre à jour", id="up-run", variant="primary")
            yield Button("Arrêter", id="up-stop", variant="error", disabled=True)
            yield Static("", id="up-hint")
        yield Static("", id="up-progress")
        with Horizontal(id="up-middle"):
            yield DataTable(id="up-files", zebra_stripes=True, cursor_type="none")
            yield Static("", id="up-result")
        yield Static(legend(), id="up-legend")
        yield Label("Historique des mises à jour", classes="up-title")
        yield DataTable(id="up-history", zebra_stripes=True, cursor_type="row")
        yield RichLog(id="up-log", wrap=True, markup=False, highlight=False, max_lines=2000)

    def on_mount(self) -> None:
        files = self.query_one("#up-files", DataTable)
        # "recopié": bytes the device already had (the installed version, or this one's earlier files).
        for label, width in (("fichier", 28), ("taille", 9), ("d'où viennent ses octets", 24), ("recopié", 8),
                             ("téléchargé", 10)):
            files.add_column(label, width=width)
        history = self.query_one("#up-history", DataTable)
        for label, width in (("quand", 16), ("de", 17), ("vers", 17), ("comment", 18), ("téléchargé", 10),
                             ("du complet", 10), ("durée", 8), ("résultat", 40)):
            history.add_column(label, width=width)
        self.query_one("#up-files").display = False
        self.query_one("#up-result").display = False
        self.query_one("#up-legend").display = False
        self.describe()
        self.show_history()
        self.set_interval(1 / 8, self.tick)

    def say(self, text: str | Text) -> None:
        self.messages.append(text.plain if isinstance(text, Text) else text)
        self.query_one("#up-log", RichLog).write(text)

    # ── state ────────────────────────────────────────────────────────────────────────

    def describe(self) -> None:
        """What is installed, what the server has, what an update would cost."""
        installed: Installed | None = self.app.installed
        version = installed.version if installed else None
        text = Text()
        if installed:
            text.append("Installée  ", style="bold")
            text.append(version, style=f"bold {GREEN}")
            text.append(f"  ·  {megabytes(installed.latest.get('total_bytes'))}\n", style="dim")
        else:
            text.append("Aucune version installée.\n", style=f"bold {ORANGE}")
        if self.latest:
            text.append("Serveur    ", style="bold")
            text.append(self.latest["version"], style="bold")
            text.append(f"  ·  {megabytes(self.latest.get('total_bytes'))}\n", style="dim")
        else:
            text.append("Serveur    pas encore interrogé : « Vérifier »\n", style="dim")
        if self.plan and self.plan.get("to") != version:
            text.append(f"\nMise à jour ({METHODS.get(self.plan['method'], self.plan['method'])}) : ", style=BLUE)
            text.append(f"{megabytes(self.plan['bytes'])} à télécharger", style=f"bold {BLUE}")
            if self.plan.get("full_bytes") and self.plan["method"] == "delta":
                text.append(f"  ({percent(self.plan['bytes'], self.plan['full_bytes'])} du paquet complet)", style=BLUE)
        elif self.latest and version == self.latest.get("version"):
            text.append("\nÀ jour.", style=f"bold {GREEN}")
        if not installed:
            text.append("\n« Mettre à jour » installe france-live depuis la livraison officielle : le paquet "
                        "complet, puis chaque jour une petite différence.", style="dim")
        self.query_one("#up-state", Static).update(text)
        self.query_one("#up-offers", Static).update(offers_text(self.latest, version))
        self.query_one("#up-offers").display = self.latest is not None
        self.hint()

    def hint(self) -> None:
        partial = self.app.sync_root / ".download"
        waiting = partial.is_dir() and any(partial.iterdir())
        text = "Un téléchargement interrompu attend : la prochaine mise à jour le reprendra." if waiting and \
            self.running is None else ""
        self.query_one("#up-hint", Static).update(text)

    def show_history(self) -> None:
        table = self.query_one("#up-history", DataTable)
        table.clear()
        for e in history_module.load(self.app.data_root / "history.json"):
            when = e.get("at", "")[:16].replace("T", " ")
            full = e.get("full_bytes")
            got = e.get("downloaded")
            if e.get("ok"):
                result = Text("✓ installée", style=GREEN)
                if e.get("resumed_from"):
                    result.append(f" · reprise à {megabytes(e['resumed_from'])}", style="dim")
            else:
                result = Text(f"✗ {e.get('error', '?')}"[:40], style=RED)
            table.add_row(when, e.get("from") or "–", e.get("to") or "–", METHODS.get(e.get("method"), e.get("method") or "–"),
                          megabytes(got) if got is not None else "–",
                          percent(got, full) if got is not None and full else "–",
                          duration_text(e.get("seconds") or 0), result)

    # ── running SyncKt ───────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#up-check")
    def check(self) -> None:
        self.start(check=True)

    @on(Button.Pressed, "#up-run")
    def update(self) -> None:
        self.start(check=False)

    @on(Button.Pressed, "#up-stop")
    def stop(self) -> None:
        if self.running is not None and not self.checking:
            self.stopped = True
            self.running.stop()

    def start(self, check: bool) -> bool:
        if self.running is not None:
            return False
        settings = self.app.settings
        self.running = self.runner(self.app.sync_root, settings.server.base_url, settings.server.epoch, check=check,
                                   java=settings.engine.java or None)
        self.checking, self.stopped = check, False
        if not check:
            self._reset_run()
            self.started = time.perf_counter()
            self.query_one("#up-files", DataTable).clear()
            self.query_one("#up-progress", Static).update("")
            self.query_one("#up-result", Static).update(Text("En cours…", style="dim"))
            for widget in ("#up-files", "#up-result", "#up-legend"):
                self.query_one(widget).display = True
        self.query_one("#up-check", Button).disabled = True
        self.query_one("#up-run", Button).disabled = True
        self.query_one("#up-stop", Button).disabled = check
        self.say(Text(f"▶ {'Vérification' if check else 'Mise à jour'}  ({dt.datetime.now():%H:%M:%S})",
                      style=f"bold {BLUE}"))
        self.hint()
        self.follow(self.running)
        return True

    @work(thread=True, exclusive=True, group="sync")
    def follow(self, run: SyncRun) -> None:
        for event in run.events():
            self.app.call_from_thread(self.apply, event)
        self.app.call_from_thread(self.finished, run)

    def apply(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "latest":
            self.latest = event
            self.describe()
        elif kind == "plan":
            self.plan = event
            if not self.checking:
                self.run_plan = event
                self.say(f"{METHODS.get(event['method'], event['method'])} : {megabytes(event['bytes'])} à télécharger")
            self.describe()
        elif kind == "up_to_date":
            self.plan = None
            self.describe()
            self.say(Text(f"À jour : {event['version']}", style=GREEN))
        elif kind == "progress":
            self.on_progress(event["done"], event["total"])
        elif kind == "file":
            self.files.append(event)
            copied = (event.get("copied") or 0) + (event.get("reused") or 0)
            self.query_one("#up-files", DataTable).add_row(
                event["path"][:28], megabytes(event["bytes"]), share_bar(event), percent(copied, event["bytes"]),
                megabytes(event.get("inserted") or 0))
        elif kind == "switched":
            self.say(Text(f"basculé sur {event['version']}", style=GREEN))
        elif kind == "done":
            self.done = event
            seconds = time.perf_counter() - self.started if self.started else 0
            self.query_one("#up-result", Static).update(result_text(event, self.run_plan, seconds, len(self.files)))
            self.say(Text(f"✓ {event['version']} installée ({METHODS.get(event['method'], event['method'])}, "
                          f"{megabytes(event['downloaded'])} téléchargés)", style=f"bold {GREEN}"))
        elif kind == "error":
            self.error = event
            self.say(Text(f"✗ {event.get('kind')}: {event.get('message')}", style=f"bold {RED}"))

    def on_progress(self, done: int, total: int) -> None:
        now = time.perf_counter()
        if self._first is None:
            self._first = (now, done)
            self.resumed_from = done if done < total else 0
        elif now > self._first[0]:
            self.speed = (done - self._first[1]) / (now - self._first[0])
        self.progress = (done, total)
        self.draw_progress()

    def draw_progress(self) -> None:
        if self.progress is None:
            return
        done, total = self.progress
        self.query_one("#up-progress", Static).update(progress_text(
            done, total, self.speed, self.frame, finished=self.running is None or done >= total,
            resumed_from=self.resumed_from))

    def tick(self) -> None:
        self.frame += 1
        if self.running is not None and not self.checking:
            self.draw_progress()

    def finished(self, run: SyncRun) -> None:
        self.running = None
        for button in ("#up-check", "#up-run"):
            self.query_one(button, Button).disabled = False
        self.query_one("#up-stop", Button).disabled = True
        if not self.checking:
            seconds = time.perf_counter() - self.started
            error = self.error
            if self.stopped:
                error = {"kind": "Arrêtée", "message": "à la demande ; le téléchargement partiel sera repris"}
                self.say(Text("Arrêtée : la version installée n'a pas bougé, la suite du téléchargement attend.",
                              style=ORANGE))
            if self.done is None and error is not None:
                self.query_one("#up-result", Static).update(Text.assemble(
                    ("✗ pas de nouvelle version\n\n", f"bold {RED}"), (f"{error.get('kind')} : {error.get('message')}\n\n", ""),
                    ("La version installée est intacte et reste en service.", "dim")))
            if self.done is not None or error is not None:
                history_module.append(self.app.data_root / "history.json",
                                      history_module.entry(self.run_plan, self.done, error, seconds, self.resumed_from))
                self.show_history()
            if self.done is not None:
                self.plan = None
            self.draw_progress()
        self.app.sync_finished(run)
        self.describe()
