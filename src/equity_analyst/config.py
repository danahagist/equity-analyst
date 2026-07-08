"""Runtime configuration: filesystem paths and environment-derived settings.

Kept deliberately small and dependency-free. Secrets (API keys) are read from
the environment; a ``.env`` file, if present, is loaded first as a convenience.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root = two levels up from this file (src/equity_analyst/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def load_dotenv(path: Path | None = None) -> None:
    """Populate ``os.environ`` from a ``.env`` file without overriding existing keys.

    Intentionally tiny (no python-dotenv dependency). Supports ``KEY=value`` lines,
    ``#`` comments, blank lines, and surrounding quotes. Missing file is a no-op.
    """
    env_path = path or (PROJECT_ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Resolved settings for a run."""

    data_dir: Path = DEFAULT_DATA_DIR
    outputs_dir: Path = DEFAULT_OUTPUTS_DIR
    anthropic_api_key: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "equity_analyst.db"

    @property
    def runs_dir(self) -> Path:
        """Scratch space for in-progress committee sessions (packets, verdicts)."""
        return self.data_dir / "runs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)


def get_settings(*, load_env: bool = True) -> Settings:
    """Build :class:`Settings` from the environment (loading ``.env`` first)."""
    if load_env:
        load_dotenv()
    data_dir = Path(os.environ.get("EQUITY_ANALYST_DATA_DIR", DEFAULT_DATA_DIR))
    outputs_dir = Path(os.environ.get("EQUITY_ANALYST_OUTPUTS_DIR", DEFAULT_OUTPUTS_DIR))
    return Settings(
        data_dir=data_dir,
        outputs_dir=outputs_dir,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
