"""JARVIS — Application Configuration.

Centralized, validated settings loaded from environment variables.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    secret_key: str = "change-me-to-a-random-string"

    # Database
    db_url: str = "sqlite+aiosqlite:///./data/jarvis.db"

    # Sandbox
    sandbox_root: Path = Path("./sandbox")
    workspace_root: Path = Path("./workspace")

    # Budget
    monthly_budget_usd: float = 25.00
    daily_budget_usd: float = 3.00
    per_task_budget_usd: float = 0.50

    @property
    def sandbox_path(self) -> Path:
        p = self.sandbox_root.resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def workspace_path(self) -> Path:
        p = self.workspace_root.resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
