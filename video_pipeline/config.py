"""Configuration shared by the legacy pipeline scripts.

Process environment values take precedence over the local .env file. Paths are
anchored to this file so scripts do not depend on the shell's working directory.
"""

from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"


def _read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    with path.open(encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_FILE_VALUES = _read_env_file()


def get_setting(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, _FILE_VALUES.get(name, default))


def require_setting(name: str) -> str:
    value = get_setting(name)
    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required setting {name}. Set it in the environment or {ENV_FILE}."
        )
    return value


FILE_NAME = require_setting("FILE_NAME")
MUSIC = get_setting("MUSIC", "1") or "1"
FPS = get_setting("FPS", "30") or "30"
