from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")

    allow_public_register: bool = Field(default=False, validation_alias="ALLOW_PUBLIC_REGISTER")
    password_min_length: int = Field(default=8, validation_alias="PASSWORD_MIN_LENGTH")

    public_app_url: str | None = Field(default=None, validation_alias="PUBLIC_APP_URL")
    password_reset_token_minutes: int = Field(default=60, validation_alias="PASSWORD_RESET_TOKEN_MINUTES")

    bootstrap_admin_name: str | None = Field(default=None, validation_alias="BOOTSTRAP_ADMIN_NAME")
    bootstrap_admin_password: str | None = Field(default=None, validation_alias="BOOTSTRAP_ADMIN_PASSWORD")

    database_url: str = Field(validation_alias="DATABASE_URL")
    redis_url: str = Field(validation_alias="REDIS_URL")

    rq_queue_import: str = Field(default="corelms_import", validation_alias="RQ_QUEUE_IMPORT")
    rq_queue_regen: str = Field(default="corelms_regen", validation_alias="RQ_QUEUE_REGEN")
    rq_queue_cleanup: str = Field(default="corelms_cleanup", validation_alias="RQ_QUEUE_CLEANUP")
    rq_queue_default: str = Field(default="corelms", validation_alias="RQ_QUEUE_DEFAULT")

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return v
        if s.startswith("postgres://"):
            # Heroku-style
            s = "postgresql://" + s[len("postgres://") :]
        if s.startswith("postgresql://") and "+" not in s.split("://", 1)[0]:
            # Force psycopg v3 driver to avoid implicit psycopg2 dependency.
            s = "postgresql+psycopg://" + s[len("postgresql://") :]
        return s

    jwt_secret_key: str = Field(validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_token_minutes: int = Field(default=15, validation_alias="JWT_ACCESS_TOKEN_MINUTES")
    jwt_issuer: str = Field(default="corelms", validation_alias="JWT_ISSUER")

    session_refresh_token_days: int = Field(default=30, validation_alias="SESSION_REFRESH_TOKEN_DAYS")
    session_idle_timeout_hours: int = Field(default=12, validation_alias="SESSION_IDLE_TIMEOUT_HOURS")
    session_absolute_timeout_days: int = Field(default=30, validation_alias="SESSION_ABSOLUTE_TIMEOUT_DAYS")

    cors_allow_origins: str = Field(validation_alias="CORS_ALLOW_ORIGINS")
    cors_allow_methods: str = Field(default="*", validation_alias="CORS_ALLOW_METHODS")
    cors_allow_headers: str = Field(default="*", validation_alias="CORS_ALLOW_HEADERS")

    enable_inprocess_scheduler: bool = Field(default=False, validation_alias="ENABLE_INPROCESS_SCHEDULER")
    cron_secret: str | None = Field(default=None, validation_alias="CRON_SECRET")

    auto_migrate_on_start: bool = Field(default=False, validation_alias="AUTO_MIGRATE_ON_START")

    trust_proxy_headers: bool = Field(default=False, validation_alias="TRUST_PROXY_HEADERS")

    s3_endpoint_url: str = Field(validation_alias="S3_ENDPOINT_URL")
    s3_public_endpoint_url: str | None = Field(default=None, validation_alias="S3_PUBLIC_ENDPOINT_URL")
    s3_access_key_id: str = Field(validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field(validation_alias="S3_BUCKET")
    s3_region_name: str = Field(default="us-east-1", validation_alias="S3_REGION_NAME")

    s3_presign_download_expires_seconds: int = Field(default=900, validation_alias="S3_PRESIGN_DOWNLOAD_EXPIRES_SECONDS")
    s3_presign_upload_expires_seconds: int = Field(default=3600, validation_alias="S3_PRESIGN_UPLOAD_EXPIRES_SECONDS")
    s3_presign_multipart_part_expires_seconds: int = Field(default=3600, validation_alias="S3_PRESIGN_MULTIPART_PART_EXPIRES_SECONDS")

    s3_connect_timeout_seconds: float = Field(default=3.0, validation_alias="S3_CONNECT_TIMEOUT_SECONDS")
    s3_read_timeout_seconds: float = Field(default=60.0, validation_alias="S3_READ_TIMEOUT_SECONDS")
    s3_max_attempts: int = Field(default=5, validation_alias="S3_MAX_ATTEMPTS")
    s3_max_pool_connections: int = Field(default=50, validation_alias="S3_MAX_POOL_CONNECTIONS")
    s3_addressing_style: str = Field(default="path", validation_alias="S3_ADDRESSING_STYLE")

    uploads_admin_ttl_hours: int = Field(default=6, validation_alias="UPLOADS_ADMIN_TTL_HOURS")
    uploads_admin_cleanup_interval_minutes: int = Field(default=15, validation_alias="UPLOADS_ADMIN_CLEANUP_INTERVAL_MINUTES")

    uploads_admin_multipart_ttl_hours: int = Field(default=12, validation_alias="UPLOADS_ADMIN_MULTIPART_TTL_HOURS")
    uploads_admin_multipart_max_abort: int = Field(default=200, validation_alias="UPLOADS_ADMIN_MULTIPART_MAX_ABORT")

    regen_ai_budget_seconds_per_lesson: float = Field(
        default=300.0,
        validation_alias="REGEN_AI_BUDGET_SECONDS_PER_LESSON",
    )
    regen_max_lesson_attempts: int = Field(
        default=2,
        validation_alias="REGEN_MAX_LESSON_ATTEMPTS",
    )

    import_zip_max_uncompressed_bytes: int = Field(default=10_000_000_000, validation_alias="IMPORT_ZIP_MAX_UNCOMPRESSED_BYTES")
    import_zip_max_files: int = Field(default=20000, validation_alias="IMPORT_ZIP_MAX_FILES")
    import_zip_max_entry_bytes: int = Field(default=3_000_000_000, validation_alias="IMPORT_ZIP_MAX_ENTRY_BYTES")
    import_zip_max_compression_ratio: int = Field(default=250, validation_alias="IMPORT_ZIP_MAX_COMPRESSION_RATIO")

    openrouter_enabled: bool = Field(default=False, validation_alias="OPENROUTER_ENABLED")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL")
    openrouter_model: str = Field(default="openai/gpt-4o-mini", validation_alias="OPENROUTER_MODEL")
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    openrouter_http_referer: str | None = Field(default=None, validation_alias="OPENROUTER_HTTP_REFERER")
    openrouter_app_title: str | None = Field(default=None, validation_alias="OPENROUTER_APP_TITLE")

    @field_validator("openrouter_enabled", mode="after")
    @classmethod
    def _auto_enable_openrouter(cls, v: bool, info):
        try:
            if bool(v):
                return True
            # Check if API key is present in validation info
            key = str(getattr(info, "data", {}).get("openrouter_api_key") or "").strip()
            return bool(key)
        except Exception:
            return v

    openrouter_timeout_connect: float = Field(default=3.0, validation_alias="OPENROUTER_TIMEOUT_CONNECT")
    openrouter_timeout_read: float = Field(default=15.0, validation_alias="OPENROUTER_TIMEOUT_READ")
    openrouter_timeout_write: float = Field(default=15.0, validation_alias="OPENROUTER_TIMEOUT_WRITE")
    openrouter_temperature: float = Field(default=0.2, validation_alias="OPENROUTER_TEMPERATURE")

    llm_provider_order: str = Field(default="openrouter", validation_alias="LLM_PROVIDER_ORDER")

    llm_debug_save: bool = Field(default=False, validation_alias="LLM_DEBUG_SAVE")
    llm_debug_log: bool = Field(default=False, validation_alias="LLM_DEBUG_LOG")
    llm_debug_max_chars: int = Field(default=2000, validation_alias="LLM_DEBUG_MAX_CHARS")


settings = Settings()


def _is_prod() -> bool:
    return (settings.app_env or "").strip().lower() in {"prod", "production"}


if _is_prod():
    if not settings.jwt_secret_key or settings.jwt_secret_key.strip().lower() in {"change-me", "your-secret", "secret"}:
        raise RuntimeError("JWT_SECRET_KEY must be set to a strong value in production")
    if bool(settings.allow_public_register):
        raise RuntimeError("ALLOW_PUBLIC_REGISTER must be false in production")

    if settings.database_url.strip() == "postgresql+psycopg://sdlp:sdlp@postgres:5432/sdlp":
        raise RuntimeError("DATABASE_URL must be set to a non-default value in production")
    if settings.redis_url.strip() == "redis://redis:6379/0":
        raise RuntimeError("REDIS_URL must be set to a non-default value in production")

    # Fail-fast if default DB credentials are still present.
    # We intentionally check the full URL string to keep this guard lightweight.
    db_url_l = (settings.database_url or "").strip().lower()
    if any(s in db_url_l for s in {"//sdlp:sdlp@", "//postgres:postgres@", "//admin:admin@"}):
        raise RuntimeError("DATABASE_URL must not use default credentials in production")

    if (settings.s3_access_key_id or "").strip().lower() in {"change-me", "your-access-key"}:
        raise RuntimeError("S3_ACCESS_KEY_ID must be set to a non-default value in production")
    if (settings.s3_secret_access_key or "").strip() in {"change-me", "your-secret-key"}:
        raise RuntimeError("S3_SECRET_ACCESS_KEY must be set to a non-default value in production")

    if bool(settings.openrouter_enabled):
        if not (settings.openrouter_api_key or "").strip():
            raise RuntimeError("OPENROUTER_API_KEY must be set when OpenRouter is enabled in production")
