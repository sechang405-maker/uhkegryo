"""공통 설정: 환경변수 로드·검증."""
import os
import warnings
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import UUID
from pydantic import AliasChoices, Field, model_validator
from typing import Literal
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict


APPROVED_LOCAL_CODEX_OWNER_ACCOUNT_ID = UUID('eb6bc5d0-d8ec-456e-b7be-db819c1a0e4c')
APPROVED_LOCAL_OLLAMA_MODEL = 'qwen3.5:4b-q4_K_M'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    llm_backend: Literal['openrouter', 'codex-cli', 'ollama'] = 'openrouter'
    codex_timeout_seconds: float = Field(default=180, ge=10, le=300)
    codex_bin_dir: str = ''
    codex_executable: str = ''
    codex_owner_account_id: UUID | None = None
    local_profile_token: str = Field(default='', repr=False)
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = APPROVED_LOCAL_OLLAMA_MODEL
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # 기본 해석 LLM (T14, services/llm.py)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    llm_timeout_seconds: float = 180.0
    llm_max_tokens: int = 800
    interpreter_prompt_version: str = "uhkegryo-interpreter-v0"
    interpreter_prompt_path: str = ""  # INTERPRETER_PROMPT_PATH env var로도 설정 가능 (pydantic-settings)
    structured_output_skill_path: str = "skills/structured-output/SKILL.md"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST", "langfuse_host"),
    )

    # DB (필수, 기본값 없음 — Neon PostgreSQL 사용)
    database_url: str

    # 앱
    runtime_mode: Literal['standard', 'anonymous_portfolio'] = 'standard'
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    # Isolated, explicitly started instructor portfolio runtime.
    portfolio_public_origin: str = ''
    portfolio_evaluation_ends_at: datetime | None = None
    portfolio_free_model_allowlist: str = ''
    portfolio_daily_llm_call_limit: int = Field(default=40, ge=1, le=40)
    portfolio_model_catalog_path: str = ''
    portfolio_model_catalog_max_age_seconds: int = Field(default=3600, ge=60, le=86400)

    # Invitation-only Google login. `local` preserves the existing private runtime.
    auth_mode: Literal['local', 'google_invite'] = 'local'
    # Explicit, development-only mode for validating Google sign-in without
    # enabling model-backed features or supplying an OpenRouter credential.
    login_test_mode: bool = False
    google_client_id: str = ''
    google_client_secret: str = Field(default='', repr=False)
    google_redirect_uri: str = ''
    auth_frontend_origin: str = 'http://localhost:3100'
    invite_code_pepper: str = Field(default='', repr=False)
    invite_redeem_attempt_limit: int = Field(default=5, ge=1, le=20)
    invite_redeem_window_seconds: int = Field(default=900, ge=60, le=3600)

    # MCP (기본 비활성화 — 실제 도구 준비 후 true로 변경)
    mcp_enabled: bool = False
    mcp_base_url: str = ""

    # TERM_CARD 카탈로그 경로
    term_cards_path: str = "/app/term-cards"

    # PostgreSQL Job worker
    worker_concurrency: int = Field(default=5, ge=1)

    # Pinterest 검색 URL 기본 템플릿 (provider 계약 확정 전 결정론 기본값, T16에서 교체)
    pinterest_search_base_url: str = "https://www.pinterest.com/search/pins/"

    # Self-hosted SearXNG Search API
    searxng_base_url: str = ""

    @property
    def is_portfolio(self) -> bool:
        return self.runtime_mode == 'anonymous_portfolio'

    @property
    def portfolio_free_models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            value.strip() for value in self.portfolio_free_model_allowlist.split(',')
            if value.strip()
        ))

    def portfolio_is_expired(self, *, now: datetime | None = None) -> bool:
        if not self.is_portfolio or self.portfolio_evaluation_ends_at is None:
            return False
        current = now or datetime.now(timezone.utc)
        return current.astimezone(timezone.utc) >= self.portfolio_evaluation_ends_at.astimezone(
            timezone.utc
        )

    @model_validator(mode='after')
    def local_codex_boundary(self):
        if self.is_portfolio:
            if self.llm_backend == 'openrouter':
                if not self.openrouter_api_key:
                    raise ValueError('Portfolio mode requires a server-only OpenRouter API key')
                if self.openrouter_base_url.rstrip('/') != 'https://openrouter.ai/api/v1':
                    raise ValueError('Portfolio mode requires the official OpenRouter base URL')
                models = self.portfolio_free_models
                if not models or any(not model.endswith(':free') for model in models):
                    raise ValueError('Portfolio allowlist must contain only explicit :free model IDs')
                if not self.llm_model.endswith(':free'):
                    raise ValueError('Portfolio mode requires an explicit free model')
                if self.llm_model not in models:
                    raise ValueError('Portfolio model must be present in the approved allowlist')
            elif self.llm_backend == 'ollama':
                local = urlsplit(self.ollama_base_url)
                try:
                    local_port = local.port
                except ValueError as error:
                    raise ValueError('Ollama requires the approved loopback URL') from error
                if (
                    local.scheme != 'http'
                    or local.hostname not in ('127.0.0.1', '::1', 'localhost')
                    or local_port != 11434
                    or local.path.rstrip('/') != '/v1'
                    or local.username is not None
                    or local.password is not None
                    or local.query
                    or local.fragment
                ):
                    raise ValueError('Ollama requires the approved loopback URL')
                if self.ollama_model != APPROVED_LOCAL_OLLAMA_MODEL:
                    raise ValueError('Ollama requires the approved local model')
                if self.openrouter_api_key:
                    raise ValueError('Ollama portfolio mode forbids an OpenRouter API key')
                if self.portfolio_free_model_allowlist or self.portfolio_model_catalog_path:
                    raise ValueError('Ollama portfolio mode forbids external model configuration')
                self.llm_model = self.ollama_model
            else:
                raise ValueError('Portfolio mode requires OpenRouter or local Ollama and forbids Codex fallback')
            if self.worker_concurrency != 1:
                raise ValueError('Portfolio mode requires exactly one worker')
            if self.environment != 'production':
                raise ValueError('Portfolio mode requires production cookie security')
            if self.auth_mode != 'local':
                raise ValueError('Portfolio mode is anonymous and cannot enable Google invite auth')
            if self.langfuse_public_key or self.langfuse_secret_key:
                raise ValueError('Portfolio mode forbids Langfuse question tracing')
            if self.mcp_enabled or self.mcp_base_url:
                raise ValueError('Portfolio mode forbids remote MCP configuration')
            if not self.portfolio_public_origin:
                raise ValueError('Portfolio mode requires an explicit public origin')
            if self.llm_backend == 'openrouter' and not self.portfolio_model_catalog_path:
                raise ValueError('Portfolio mode requires an approved model catalog path')
            public = urlsplit(self.portfolio_public_origin)
            if (
                public.scheme != 'https' or not public.netloc
                or public.path not in ('', '/') or public.query or public.fragment
                or public.username is not None or public.password is not None
            ):
                raise ValueError('Portfolio public origin must be an HTTPS origin without credentials or a path')
            origins = tuple(
                value.strip().rstrip('/') for value in self.allowed_origins.split(',')
                if value.strip()
            )
            if origins != (self.portfolio_public_origin.rstrip('/'),):
                raise ValueError('Portfolio CORS origin must exactly match the public origin')
            if self.portfolio_evaluation_ends_at is None:
                raise ValueError('Portfolio mode requires an evaluation end time')
            end_time = self.portfolio_evaluation_ends_at
            if end_time.tzinfo is None or end_time.utcoffset() is None:
                raise ValueError('Portfolio evaluation end time must include a timezone')
            if end_time <= datetime.now(timezone.utc):
                raise ValueError('Portfolio evaluation end time must be in the future')
            return self
        if self.login_test_mode and (
            self.auth_mode != 'google_invite' or self.environment != 'development'
        ):
            raise ValueError(
                'LOGIN_TEST_MODE requires Google invite auth in development'
            )
        if self.auth_mode == 'google_invite':
            required = (self.google_client_id, self.google_client_secret,
                        self.google_redirect_uri, self.invite_code_pepper)
            if not all(required) or len(self.invite_code_pepper) < 16:
                raise ValueError('Google invite mode requires OIDC settings and a strong invite pepper')
            frontend = urlsplit(self.auth_frontend_origin)
            redirect = urlsplit(self.google_redirect_uri)
            if frontend.scheme not in ('http', 'https') or not frontend.netloc or frontend.path not in ('', '/'):
                raise ValueError('AUTH_FRONTEND_ORIGIN must be an origin without a path')
            if redirect.scheme not in ('http', 'https') or not redirect.netloc:
                raise ValueError('GOOGLE_REDIRECT_URI must be an absolute URL')
        if self.llm_backend != 'codex-cli':
            return self
        if (
            self.auth_mode == 'google_invite'
            and self.codex_owner_account_id != APPROVED_LOCAL_CODEX_OWNER_ACCOUNT_ID
        ):
            raise ValueError('Google invite Codex mode requires the approved owner account ID')
        if self.auth_mode == 'google_invite' and (
            frontend.scheme != 'http'
            or frontend.hostname not in ('127.0.0.1', '::1', 'localhost')
            or frontend.port != 3110
            or frontend.username is not None
            or frontend.password is not None
            or redirect.scheme != 'http'
            or redirect.hostname not in ('127.0.0.1', '::1', 'localhost')
            or redirect.port != 8010
            or redirect.username is not None
            or redirect.password is not None
            or redirect.path != '/api/auth/google/callback'
            or redirect.query
            or redirect.fragment
        ):
            raise ValueError('Google invite Codex mode requires loopback OAuth ports 8010/3110')
        db = urlsplit(self.database_url)
        if (db.scheme not in ('postgresql', 'postgres') or db.hostname not in ('127.0.0.1', '::1', 'localhost')
                or db.query or db.fragment):
            raise ValueError('Codex mode requires a loopback PostgreSQL URL without query overrides')
        if self.environment != 'development' or self.worker_concurrency != 1:
            raise ValueError('Codex mode requires development and exactly one worker')
        if self.langfuse_public_key or self.langfuse_secret_key or self.mcp_enabled or self.mcp_base_url:
            raise ValueError('Codex mode does not enable remote tracing or MCP')
        if self.searxng_base_url:
            search = urlsplit(self.searxng_base_url)
            if (search.scheme != 'http' or search.hostname not in ('127.0.0.1', '::1', 'localhost')
                    or search.username is not None or search.password is not None
                    or search.path not in ('', '/') or search.query or search.fragment):
                raise ValueError('Codex image search requires a loopback SearXNG origin')
            _ = search.port  # Reject malformed ports before any request.
        if self.interpreter_prompt_version != 'uhkegryo-interpreter-v4':
            raise ValueError('Codex mode requires the v4 structured interpreter prompt')
        self.llm_model = 'gpt-5.6-luna'
        return self


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # SQLite 사용 시 경고 (운영 환경 부적합)
    if s.database_url.startswith("sqlite"):
        warnings.warn(
            "SQLite는 운영 환경용이 아닙니다. PostgreSQL(postgresql://) 사용 권장.",
            RuntimeWarning,
            stacklevel=2,
        )
    return s


def resolve_term_cards_dir(settings: Settings | None = None) -> Path:
    """TERM_CARD 디렉터리 경로 해결.
    
    우선순위:
    1. TERM_CARDS_PATH 환경변수 (settings.term_cards_path)
    2. Docker 기본 경로: /app/term-cards
    3. 로컬 개발: 레포 루트/docs/domains/illustration-reference/term-cards/
    4. 모두 실패 시 예외 발생
    """
    if settings is None:
        settings = get_settings()
    
    # 1. 환경변수/설정에서 지정한 경로
    configured_path = Path(settings.term_cards_path)
    if configured_path.exists():
        return configured_path
    
    # 2. Docker 기본 경로
    docker_path = Path("/app/term-cards")
    if docker_path.exists():
        return docker_path
    
    # 3. 로컬 개발: 현재 파일 기준 레포 루트 탐색
    current_file = Path(__file__).resolve()
    # backend/shared/config.py -> backend/ -> proj2-4/
    repo_root = current_file.parent.parent.parent
    local_path = repo_root / "docs" / "domains" / "illustration-reference" / "term-cards"
    if local_path.exists():
        return local_path
    
    # 4. 모두 실패
    raise FileNotFoundError(
        f"TERM_CARD 디렉터리를 찾을 수 없습니다. "
        f"다음을 확인하세요: "
        f"TERM_CARDS_PATH={settings.term_cards_path}, "
        f"Docker경로=/app/term-cards, "
        f"로컬경로={local_path}"
    )
