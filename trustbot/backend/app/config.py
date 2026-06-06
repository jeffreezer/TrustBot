"""Application configuration, loaded entirely from environment variables.

Keeping all config in the environment is what makes the same image run locally,
on GCP, or on AWS with only a config change.
"""
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Non-production environments. Two consequences, both fail-closed: read-only
# debug/introspection endpoints are exposed only here, and credential-bearing
# config may fall back to a local default only here. Anything not in this set
# (prod, staging, or an unrecognized value) is treated as production.
DEBUG_ENABLED_ENVS = frozenset({"local", "dev", "development", "test"})

# Credential-free local fallback for DATABASE_URL (no embedded user:pass). Used
# only in the non-production environments above when no URL is supplied — so the
# code never carries a hard-coded credential.
_LOCAL_DB_FALLBACK = "postgresql+psycopg://localhost:5432/trustbot"


class Settings(BaseSettings):
    # protected_namespaces=() avoids pydantic warnings on the MODEL_* fields.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    app_env: str = "local"

    # Database (Postgres + pgvector). Read from the environment; no credentials
    # are baked into the code. Validated below (fail-closed outside local/dev/test).
    database_url: str = ""

    # Cloud SQL via unix socket (Cloud Run): when DATABASE_URL is empty but these parts
    # are set, the URL is composed below. db_password comes from Secret Manager via the
    # DB_PASSWORD env (--set-secrets) — referenced by name, never committed/hardcoded.
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""
    cloud_sql_instance: str = ""  # PROJECT:REGION:INSTANCE connection name

    # API
    cors_origins: str = "http://localhost:3000"

    # Object storage. "local" | "s3" (MinIO/S3) | "gcs" (Google Cloud Storage).
    storage_backend: str = "local"
    local_storage_dir: str = "./_storage"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "trustbot-evidence"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Optional S3 server-side encryption (e.g. "AES256" or "aws:kms"). Left empty
    # by default so the local MinIO demo isn't broken; enable in cloud.
    s3_sse: str = ""

    # Google Cloud Storage backend (STORAGE_BACKEND=gcs). Authenticates via ADC — on
    # Cloud Run that's the service account, so there are no static keys. The bucket is
    # provisioned by deploy.sh; downloads use v4 signed, expiring URLs.
    gcs_bucket: str = ""
    gcs_project: str = ""  # optional; ADC usually infers the project
    signed_url_expiry: int = 3600  # seconds

    # Seed data location (the synthetic Northwind company). Mounted read-only in
    # docker; override for local runs.
    seed_data_dir: str = "/seed/northwind_ai"

    # Model provider (placeholders for later phases)
    model_provider: str = ""
    model_api_key: str = ""
    model_base_url: str = ""
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Pinned upstream commit revisions for the baked local models, so a future build bakes
    # the *same* bytes (reproducible, tamper-evident) instead of whatever each repo's `main`
    # points to. The running container loads these revisions offline, so they MUST equal the
    # revisions baked at build time — docker-compose drives both the build arg and this env
    # from the same variable to keep them in lockstep. Env-overridable (principle 4).
    embedding_model_revision: str = "5617a9f61b028005a4858fdac845db406aefb181"
    reranker_model_revision: str = "c5ee24cb16019beea0893ab7796b1df96625c6b8"

    # Embedding backend selected by the provider abstraction (Phase 2):
    #   "local" – BGE-M3 on CPU (default; model baked into the image at build time)
    #   "hash"  – deterministic, dependency-free fake (test suite / offline CI)
    #   "api"   – OpenAI-compatible /v1/embeddings (uses MODEL_BASE_URL + MODEL_API_KEY)
    embedding_provider: str = "local"

    # Reranker backend selected by the provider abstraction (Phase 3):
    #   "local" – ms-marco-MiniLM cross-encoder on CPU (default; baked into the image)
    #   "hash"  – deterministic lexical-overlap fake (test suite / offline CI)
    #   "none"  – passthrough; keep the fused order (no second-pass model)
    reranker_provider: str = "local"

    # Hybrid retrieval (Phase 3). candidate_k is pulled from *each* of vector and
    # keyword search before fusion; top_k is the count returned after reranking.
    retrieval_candidate_k: int = 20
    retrieval_top_k: int = 5

    # Answer generation backend (Phase 4), selected by the provider abstraction:
    #   "api"       – OpenAI-compatible /v1/chat/completions (set MODEL_BASE_URL +
    #                 MODEL_API_KEY + GENERATION_MODEL, e.g. OpenAI / vLLM / Ollama's /v1)
    #   "anthropic" – native Claude Messages API + tool-use (set MODEL_API_KEY)
    #   "fake"      – deterministic, grounding-only stand-in (tests / offline CI / demo);
    #                 never fabricates, returns 'unknown' when grounding is insufficient
    # The docker-compose demo sets "fake" so the stack runs with zero external setup.
    generation_provider: str = "api"
    # Empty = use the selected provider's own default (gpt-4o-mini for api,
    # claude-sonnet-4-6 for anthropic); set GENERATION_MODEL to override.
    generation_model: str = ""
    generation_temperature: float = 0.0
    generation_max_tokens: int = 1024

    # Character-based chunking (token-free so tests need no tokenizer/model).
    # Overlap preserves context across chunk boundaries.
    chunk_size: int = 1200
    chunk_overlap: int = 200

    # Hard cap on a single document accepted for ingestion (boundary validation).
    max_ingest_bytes: int = 10 * 1024 * 1024  # 10 MiB

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_non_production(self) -> bool:
        return self.app_env.strip().lower() in DEBUG_ENABLED_ENVS

    @property
    def debug_endpoints_enabled(self) -> bool:
        """Whether read-only debug/introspection endpoints are reachable.

        Fail-closed: only enabled in known non-production environments.
        """
        return self.is_non_production

    @model_validator(mode="after")
    def _validate_required_secrets(self) -> "Settings":
        """Fail-closed on credential-bearing config.

        Outside local/dev/test, credentials must come from the environment /
        secret manager — the service refuses to start rather than fall back to a
        default. In non-production, a credential-free local default is allowed so
        the demo and tests run with zero setup.
        """
        # Cloud SQL unix-socket path: compose the URL from parts when no full URL is
        # given. The password (from Secret Manager) is percent-encoded; the assembled
        # URL contains it, so it is never logged (see db/__init__.py).
        if (
            not self.database_url
            and self.cloud_sql_instance
            and self.db_user
            and self.db_password
            and self.db_name
        ):
            self.database_url = (
                f"postgresql+psycopg://{self.db_user}:{quote(self.db_password, safe='')}"
                f"@/{self.db_name}?host=/cloudsql/{self.cloud_sql_instance}"
            )

        if not self.database_url:
            if self.is_non_production:
                self.database_url = _LOCAL_DB_FALLBACK
            else:
                raise ValueError(
                    "DATABASE_URL must be provided via the environment when "
                    "APP_ENV is not one of local/dev/test."
                )

        # GCS uses ADC (no static keys); the only hard requirement is the bucket name.
        if (
            self.storage_backend == "gcs"
            and not self.gcs_bucket
            and not self.is_non_production
        ):
            raise ValueError(
                "GCS_BUCKET must be set when STORAGE_BACKEND=gcs outside local/dev/test."
            )

        # S3-credential checks apply only when the backend is literally s3.
        if self.storage_backend == "s3" and not self.is_non_production:
            missing = [
                key
                for key, value in (
                    ("S3_ACCESS_KEY_ID", self.s3_access_key_id),
                    ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"{', '.join(missing)} must be provided via the environment "
                    "when APP_ENV is not one of local/dev/test."
                )

        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE must be positive.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be >= 0 and < CHUNK_SIZE.")

        if self.retrieval_candidate_k <= 0:
            raise ValueError("RETRIEVAL_CANDIDATE_K must be positive.")
        if not 0 < self.retrieval_top_k <= self.retrieval_candidate_k:
            raise ValueError(
                "RETRIEVAL_TOP_K must be > 0 and <= RETRIEVAL_CANDIDATE_K."
            )

        if self.generation_temperature < 0:
            raise ValueError("GENERATION_TEMPERATURE must be >= 0.")
        if self.generation_max_tokens <= 0:
            raise ValueError("GENERATION_MAX_TOKENS must be positive.")

        return self


settings = Settings()
