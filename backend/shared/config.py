"""공통 설정: 환경변수 로드·검증."""
import os
import warnings
from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    openrouter_api_key: str = ""
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
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

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
