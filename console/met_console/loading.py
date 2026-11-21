"""The start-up screen: every loading step with a spinner and its time, under an overall bar.

The loading itself runs in a worker thread; it reports through start / progress / done /
fail (called on the UI thread), and the view animates itself at 12 frames a second.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from rich.text import Text
from textual.widget import Widget

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BLUE, LIGHT_BLUE, ORANGE, GREEN, RED = "#2a78d6", "#8fb8ef", "#eb6834", "#1baf7a", "#e34948"


def seconds_text(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s".replace(".", ",")


@dataclass
class Step:
    key: str
    label: str
    weight: float  # its share of a typical start-up, for the overall bar
    state: str = "todo"  # todo, run, done, fail
    started: float = 0.0
    seconds: float = 0.0
    detail: str = ""
    progress: float | None = None  # 0..1 when the step can tell

    def elapsed(self, now: float) -> float:
        if self.state == "run":
            return now - self.started
        return self.seconds

    def share(self, now: float) -> float:
        """How much of this step is behind us, 0..1."""
        if self.state == "done":
            return 1.0
        if self.state != "run":
            return 0.0
        if self.progress is not None:
            return self.progress
        # No progress to report: creep towards 90 % so the bar keeps moving.
        return 0.9 * (1 - math.exp(-self.elapsed(now) / max(self.weight, 0.5)))


class LoadingView(Widget):
    DEFAULT_CSS = """
    LoadingView { height: auto; padding: 1 2; }
    """
    BAR = 46
    LABEL = 38

    def __init__(self, heading: str, steps: list[tuple[str, str, float]], **kwargs):
        super().__init__(**kwargs)
        self.heading = heading
        self.steps = {key: Step(key, label, weight) for key, label, weight in steps}
        self.frame = 0
        self.started = time.perf_counter()
        self.finished: float | None = None
        self.error: str | None = None

    def on_mount(self) -> None:
        self.set_interval(1 / 12, self.tick)

    def tick(self) -> None:
        self.frame += 1
        self.refresh()

    # ── reports from the loader ──────────────────────────────────────────────────────

    def start(self, key: str, detail: str = "") -> None:
        step = self.steps[key]
        step.state, step.started, step.detail = "run", time.perf_counter(), detail
        self.refresh()

    def progress(self, key: str, fraction: float, detail: str = "") -> None:
        step = self.steps[key]
        step.progress = min(max(fraction, 0.0), 1.0)
        step.detail = detail or step.detail
        self.refresh()

    def done(self, key: str, detail: str = "") -> None:
        step = self.steps[key]
        step.state, step.seconds, step.progress = "done", time.perf_counter() - step.started, 1.0
        step.detail = detail or step.detail
        if all(s.state == "done" for s in self.steps.values()):
            self.finished = time.perf_counter()
        self.refresh()

    def fail(self, key: str, message: str) -> None:
        step = self.steps[key]
        step.state, step.seconds = "fail", time.perf_counter() - step.started
        self.error, self.finished = message, time.perf_counter()
        self.refresh()

    # ── drawing ──────────────────────────────────────────────────────────────────────

    def fraction(self, now: float) -> float:
        total = sum(s.weight for s in self.steps.values())
        return sum(s.weight * s.share(now) for s in self.steps.values()) / total

    def bar(self, fraction: float) -> Text:
        filled = round(fraction * self.BAR)
        text = Text()
        # A brighter cell runs along the filled part while loading: the "train".
        shine = self.frame % (filled + 6) if self.finished is None and filled else -1
        colour = RED if self.error else GREEN if self.finished else BLUE
        for i in range(self.BAR):
            if i < filled:
                text.append("━", style=f"bold {LIGHT_BLUE}" if i in (shine, shine - 1) else colour)
            elif i == filled and self.finished is None:
                text.append("╺", style="dim")
            else:
                text.append("━", style="dim")
        return text

    def render(self) -> Text:
        now = time.perf_counter()
        fraction = 1.0 if self.finished and not self.error else self.fraction(now)
        total = (self.finished or now) - self.started
        text = Text()
        text.append("raptor-kmp", style=f"bold {BLUE}")
        text.append(f"  ·  {self.heading}\n\n", style="bold")
        text.append_text(self.bar(fraction))
        text.append(f"  {fraction * 100:3.0f} %  ·  {seconds_text(total)}\n\n", style="dim")
        spin = SPINNER[self.frame % len(SPINNER)]
        for step in self.steps.values():
            icon, style = {"todo": ("·", "dim"), "run": (spin, f"bold {ORANGE}"), "done": ("✓", f"bold {GREEN}"),
                           "fail": ("✗", f"bold {RED}")}[step.state]
            text.append(f" {icon}  ", style=style)
            text.append(step.label.ljust(self.LABEL), style="dim" if step.state == "todo" else "")
            if step.state != "todo":
                text.append(seconds_text(step.elapsed(now)).rjust(8), style="dim" if step.state == "done" else ORANGE)
            if step.state == "run" and step.progress is not None:
                cells = round(step.progress * 12)
                text.append("  ")
                text.append("━" * cells, style=BLUE)
                text.append("━" * (12 - cells), style="dim")
            if step.detail and step.state != "todo":
                text.append(f"  {step.detail}", style="dim")
            text.append("\n")
        if self.error:
            text.append(f"\n{self.error}\n", style=RED)
        elif self.finished:
            text.append("\nC'est parti.", style=f"italic {GREEN}")
        return text
