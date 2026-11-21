"""Checking for and installing france-live versions: console/engine's SyncKt, run as a child.

SyncKt runs dataset-sync, the library the apps use, and tells each step as one JSON object per
line (installed, latest, plan or up_to_date, progress, file, switched, done, or error). The
console reads them as they come; the routing engine keeps answering on the installed version
meanwhile.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

from .paths import engine_classpath, engine_missing, java_executable

SYNC_CLASS = "eu.dotshell.met.console.SyncKt"
CITY = "france-live"


class SyncRun:
    """One check or update. `events()` yields SyncKt's lines as dicts, then ends."""

    def __init__(self, root: Path, base_url: str, epoch: str, check: bool = False, java: str | None = None,
                 popen: Callable = subprocess.Popen):
        self.command = [java_executable(java), "-Xmx256m", "-cp", engine_classpath(), SYNC_CLASS,
                        "--root", str(root), "--base-url", base_url, "--city", CITY, "--epoch", epoch]
        if check:
            self.command.append("--check")
        self._popen = popen
        self._process = None
        self.code: int | None = None

    def events(self) -> Iterator[dict]:
        missing = engine_missing() if self._popen is subprocess.Popen else None
        if missing:
            self.code = 1
            yield {"type": "error", "kind": "Setup", "message": missing}
            return
        self._process = self._popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", bufsize=1)
        last_error = None
        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue  # not one of SyncKt's lines (a JVM warning)
            if event.get("type") == "error":
                last_error = event
            yield event
        self.code = self._process.wait()
        if self.code != 0 and last_error is None:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            yield {"type": "error", "kind": "Process", "message": stderr.strip()[-400:] or f"code {self.code}"}

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
