from typing import Any

from pydantic import BaseModel


class Manifest(BaseModel):
    """Build manifest with metadata and checksums."""

    schema_version: int
    tool_version: str
    created_at_iso: str
    inputs: dict[str, Any]
    outputs: dict[str, str]  # filename -> sha256
    stats: dict[str, int]
    build: dict[str, str]
