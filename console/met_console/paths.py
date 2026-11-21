"""Where the console's files are."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parent.parent
#: Per machine and git-ignored: the installed dataset, caches, settings, update history.
DEFAULT_DATA_DIR = CONSOLE_DIR / "data"
ENGINE_DIR = CONSOLE_DIR / "engine"
ENGINE_INSTALL = ENGINE_DIR / "build" / "install" / "console-engine"
DOCS_DIR = CONSOLE_DIR / "docs"


def java_executable(java: str | None = None) -> str:
    """The `java` to run the engine with: the one given, then $JAVA_HOME, then the PATH."""
    if java:
        return java
    home = os.environ.get("JAVA_HOME")
    if home:
        candidate = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if candidate.exists():
            return str(candidate)
    return shutil.which("java") or "java"


def engine_classpath() -> str:
    return str(ENGINE_INSTALL / "lib" / "*")


def engine_missing() -> str | None:
    """Why the engine cannot start, or None."""
    if not (ENGINE_INSTALL / "lib").exists():
        return (f"le moteur n'est pas construit : dans {ENGINE_DIR.relative_to(CONSOLE_DIR.parent)}, "
                f"lance ..\\..\\gradlew.bat installDist (ou console.ps1, qui le fait)")
    return None
