from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "光伏智库 API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://solar:solar@postgres:5432/solar_rag"
    redis_url: str = "redis://redis:6379/0"
    storage_path: Path = Path("/data/knowledge")
    max_file_size_mb: int = 100
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    ai_base_url: str = ""
    ai_api_key: str = ""
    chat_model: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 1536
    rerank_model: str = ""
    ai_timeout_seconds: int = 90
    ai_offline_mode: bool = False

    admin_username: str = "admin"
    admin_password_hash: str = ""
    session_secret: str = Field(default="change-me", min_length=8)
    session_max_age_seconds: int = 8 * 60 * 60
    cookie_secure: bool = False
    rate_limit_salt: str = "change-this-rate-limit-salt"
    trust_proxy_headers: bool = True

    guest_requests_per_hour: int = 20
    global_requests_per_day: int = 500
    global_tokens_per_day: int = 2_000_000
    max_question_chars: int = 1000
    conversation_retention_days: int = 30

    chunk_min_chars: int = 500
    chunk_target_chars: int = 750
    chunk_max_chars: int = 900
    chunk_overlap_chars: int = 100
    retrieval_dense_limit: int = 30
    retrieval_keyword_limit: int = 30
    retrieval_fused_limit: int = 12
    retrieval_context_limit: int = 6

    celery_always_eager: bool = False
    use_docling: bool = True
    enable_ocr: bool = True

    @field_validator("embedding_dimension")
    @classmethod
    def valid_embedding_dimension(cls, value: int) -> int:
        if not 1 <= value <= 4000:
            raise ValueError("EMBEDDING_DIMENSION must be between 1 and 4000")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def ai_configured(self) -> bool:
        return self.ai_offline_mode or bool(
            self.ai_base_url and self.ai_api_key and self.chat_model and self.embedding_model
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

