"""Settings, read from the environment (a .env file is loaded if present)."""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    token: str
    dry_run: bool
    max_trash_per_run: int
    lookback_days: int
    triage_at: str
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.sqlite3"


def load_settings() -> Settings:
    _load_dotenv(Path(".env"))
    data_dir = Path(os.environ.get("AGENT_DATA_DIR", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        token=os.environ.get("AGENT_TOKEN", ""),
        # Default to dry run: a misconfigured install must never delete anything.
        dry_run=_bool(os.environ.get("TRIAGE_DRY_RUN", "true")),
        max_trash_per_run=int(os.environ.get("TRIAGE_MAX_TRASH_PER_RUN", "25")),
        lookback_days=int(os.environ.get("TRIAGE_LOOKBACK_DAYS", "2")),
        triage_at=os.environ.get("TRIAGE_AT", "02:30"),
        data_dir=data_dir,
    )
