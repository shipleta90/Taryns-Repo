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
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    briefing_enabled: bool = False   # turned off in the app; set BRIEFING_ENABLED=true to bring it back
    briefing_at: str = "06:30"
    briefing_max_items: int = 25
    timezone: str = "America/Los_Angeles"
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"

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
        ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
        briefing_enabled=_bool(os.environ.get("BRIEFING_ENABLED", "false")),
        briefing_at=os.environ.get("BRIEFING_AT", "06:30"),
        briefing_max_items=int(os.environ.get("BRIEFING_MAX_ITEMS", "25")),
        timezone=os.environ.get("TIMEZONE", "America/Los_Angeles"),
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-5-5"),
        claude_effort=os.environ.get("CLAUDE_EFFORT", "medium"),
    )
