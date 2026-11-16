"""Application settings, loaded from environment variables / .env.

One Settings object is the single source of configuration. Everything else
receives values from it instead of reading os.environ directly.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"  # development | test | production

    database_url: str = ""
    test_database_url: str = ""

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: str = ""
    api_base_url: str = "http://127.0.0.1:8000"

    resume_dir: Path = PROJECT_ROOT / "data" / "resumes"
    max_upload_mb: int = 5

    embedding_backend: str = "auto"  # auto | sentence-transformers | hashing
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    weight_skills: float = 0.30
    weight_semantic: float = 0.30
    weight_title: float = 0.15
    weight_experience: float = 0.10
    weight_keywords: float = 0.15

    http_timeout_seconds: float = 20.0
    http_max_retries: int = Field(default=3, ge=0, le=10)
    http_min_interval_seconds: float = 0.5

    scheduler_enabled: bool = False
    scheduler_interval_hours: float = 12.0

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def scoring_weights(self) -> dict[str, float]:
        return {
            "skills": self.weight_skills,
            "semantic": self.weight_semantic,
            "title": self.weight_title,
            "experience": self.weight_experience,
            "keywords": self.weight_keywords,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
