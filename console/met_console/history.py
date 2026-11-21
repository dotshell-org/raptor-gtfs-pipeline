"""Every update the console ran, kept in <data>/history.json: what it cost, how it went."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

KEEP = 200


def load(path: Path) -> list[dict]:
    """The updates, newest first."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return entries if isinstance(entries, list) else []


def append(path: Path, entry: dict) -> list[dict]:
    entries = [{"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **entry}] + load(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(entries[:KEEP], ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)
    return entries[:KEEP]


def entry(plan: dict | None, done: dict | None, error: dict | None, seconds: float, resumed_from: int = 0) -> dict:
    """One update as the history keeps it, from SyncKt's plan, done and error lines."""
    plan = plan or {}
    record = {"from": plan.get("from"), "to": plan.get("to"), "method": plan.get("method"),
              "plan_bytes": plan.get("bytes"), "full_bytes": plan.get("full_bytes"),
              "total_bytes": plan.get("total_bytes"), "seconds": round(seconds, 1), "ok": done is not None}
    if resumed_from:
        record["resumed_from"] = resumed_from
    if done is not None:
        record.update({k: done.get(k) for k in ("from", "version", "method", "downloaded", "download_ms", "apply_ms",
                                                "bytes", "copied", "reused", "inserted", "derived")})
        record["to"] = done.get("version")
    if error is not None:
        record["error"] = f"{error.get('kind')}: {error.get('message')}"
    return record
