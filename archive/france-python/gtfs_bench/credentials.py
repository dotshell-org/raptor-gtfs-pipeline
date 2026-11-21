"""Credentials for the feeds that need an account.

A catalogue row's `auth` column names a key: `auth=grandlyon` reads GRANDLYON_USER and
GRANDLYON_PASSWORD. Each value is looked up in benchmark/.env first, then in the
environment, and only then asked for, when the caller allows prompting (the notebook does,
a scheduled run does not).

Nothing in this module prints, logs or writes a secret: `Credentials` hides its password
from repr, and errors name the variables that are missing, never their values.
"""

from __future__ import annotations

import getpass
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class MissingCredentials(RuntimeError):
    pass


@dataclass(frozen=True)
class Credentials:
    user: str
    password: str = field(repr=False)

    def as_basic_auth(self) -> tuple[str, str]:
        return self.user, self.password


def variable_names(key: str) -> tuple[str, str]:
    prefix = key.strip().upper()
    return f"{prefix}_USER", f"{prefix}_PASSWORD"


class CredentialStore:
    """Resolves credentials by key, once each, from .env, the environment, or a prompt."""

    def __init__(
        self,
        env_file: Path | None = ENV_FILE,
        environ: Mapping[str, str] | None = None,
        interactive: bool = False,
    ):
        values = dotenv_values(env_file) if env_file is not None and Path(env_file).exists() else {}
        self._file = {k: v for k, v in values.items() if v}
        self._environ = os.environ if environ is None else environ
        self._interactive = interactive
        self._cache: dict[str, Credentials] = {}

    def _lookup(self, name: str) -> str | None:
        return self._file.get(name) or self._environ.get(name) or None

    def has(self, key: str) -> bool:
        """Whether `key` resolves without asking anyone."""
        if key in self._cache:
            return True
        user_var, password_var = variable_names(key)
        return bool(self._lookup(user_var) and self._lookup(password_var))

    def set(self, key: str, user: str, password: str) -> None:
        """Provide credentials directly, e.g. from a notebook cell that asked for them."""
        self._cache[key] = Credentials(user, password)

    def get(self, key: str) -> Credentials:
        if key in self._cache:
            return self._cache[key]
        user_var, password_var = variable_names(key)
        user, password = self._lookup(user_var), self._lookup(password_var)
        if (not user or not password) and self._interactive:
            user = user or input(f"{key} — {user_var}: ").strip()
            password = password or getpass.getpass(f"{key} — {password_var}: ")
        if not user or not password:
            raise MissingCredentials(
                f"no credentials for '{key}': set {user_var} and {password_var} in "
                f"{ENV_FILE} or in the environment"
            )
        self._cache[key] = Credentials(user, password)
        return self._cache[key]
