"""Small stdlib-only .env loader for local Ponte configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path


_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(
    path: str | Path | None = None,
    *,
    override: bool = False,
) -> dict[str, str]:
    """Load simple ``KEY=value`` entries and keep shell values by default."""

    env_path = Path(path) if path is not None else Path(os.environ.get("PONTE_ENV_FILE", DEFAULT_ENV_PATH))
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            raise ValueError(f"Invalid .env key on line {line_number}")
        value = _parse_value(raw_value.strip())
        values[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    return value
