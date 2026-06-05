"""Typed settings — single source of truth for env-driven configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM — Gemini
    google_api_key: str = ""
    gemini_model_flash: str = "gemini-2.5-flash"
    gemini_model_pro: str = "gemini-2.5-pro"
    # Backend selection: empty `vertex_project` → AI Studio (api_key auth).
    # Set vertex_project + vertex_location → Vertex AI (ADC / service account
    # auth, more reliable for production: regional endpoints, IAM, no key
    # rotation). The new google-genai SDK supports both backends.
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    # Optional explicit service-account JSON path. If empty, ADC is used
    # (gcloud auth application-default login, GOOGLE_APPLICATION_CREDENTIALS,
    # GKE workload identity, etc.).
    vertex_credentials_path: str = ""
    # Vision (VLM) model override. Empty → fall back to gemini_model_pro
    # for image-bearing calls (newer Gemini tiers support vision natively).
    gemini_vision_model: str = ""

    # LLM — Anthropic
    anthropic_api_key: str = ""
    claude_model_haiku: str = "claude-haiku-4-5"
    claude_model_sonnet: str = "claude-sonnet-4-5"
    claude_model_opus: str = "claude-opus-4-1"

    # LLM — defaults
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 4
    # 'gemini' | 'anthropic' | 'auto' (auto = follow provider_router policy)
    default_provider: str = "auto"

    # Cost
    daily_spend_cap_usd: float = 5.00
    cost_soft_warn_pct: float = 0.80
    cost_hard_cap_pct: float = 1.00
    # Cumulative cap surviving across process restarts (file-backed via
    # mdi.kernel.spend_ledger). 0 = disabled (observer mode); set to a
    # positive value to enforce a hard cumulative ceiling on LLM spend.
    # This is checked BEFORE the daily cap so the more restrictive of the
    # two wins. Useful for capped trials / time-boxed deployments.
    cumulative_spend_cap_usd: float = 0.0
    # Directory the spend ledger file lives in. Defaults to the repo root;
    # production deployments should point this at a persistent volume.
    data_dir: str = "."

    # DB
    database_url: str = "postgresql+psycopg://mdi:mdi@localhost:5432/mdi"
    database_url_async: str = "postgresql+asyncpg://mdi:mdi@localhost:5432/mdi"
    # Privileged admin DSN — used by cross-tenant admin queries that
    # need to bypass RLS (e.g. `GET /batches` in admin mode, future
    # cross-tenant reporting). Defaults to the same URL as the app
    # DSN — for single-role setups that's correct. In dev/prod where
    # the app runs under a NOBYPASSRLS role like `mdi_app`, point this
    # at the superuser DSN so admins can see across tenants.
    database_url_admin_async: str = "postgresql+asyncpg://mdi:mdi@localhost:5432/mdi"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis / queue
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 720
    # Admin auth — gates POST /admin/* endpoints (tenant onboarding, key issuance).
    # Compared via constant-time equality against the X-Admin-Key header.
    # In production this would be a separate RBAC role; for local mode an
    # env-var-managed shared secret is sufficient.
    admin_api_key: str = "local-dev-admin-key"

    # Embeddings
    embed_model: str = "BAAI/bge-m3"
    embed_device: str = "cpu"
    # When True, Hippocampus + RAG use the real sentence-transformers model
    # (semantic similarity, ~2GB download on first load, ~30s warm-up).
    # When False, a deterministic SHA-based stub is used (instant, but only
    # identical inputs hit the memory). Default is False for local-dev /
    # tests; flip to True in production to enable the full self-training loop.
    use_real_embeddings: bool = False

    # Observability
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Page-limit gate
    page_limit_soft: int = 10
    page_limit_hard: int = 200

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: str = "http://localhost:3000,http://localhost:8501"

    # Pipeline
    organ_concurrency: int = 5
    batch_timeout_seconds: int = 900

    # Conscience safety
    enable_invented_rules: bool = False
    entity_resolver_threshold: int = Field(default=85, ge=0, le=100)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def package_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def packs_dir(self) -> Path:
        return self.package_root / "packs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
