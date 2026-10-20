"""계약 enum 열거형 (docs/specs/api-contract.md 기준).

api-contract.md §35(ReasonCode)·§37(FailureCode)·각 모델 enum을 그대로 반영한다.
"""

from enum import StrEnum


class Role(StrEnum):
    """카탈로그 체택 가능 역할 (category_load_order 기준)."""

    BODY = "body"
    POSE = "pose"
    COMPOSITION = "composition"
    VIEW = "composition"  # Source compatibility; wire values are canonical.
    PERSPECTIVE = "perspective"
    LAYOUT = "composition"

    @classmethod
    def _missing_(cls, value):
        if value in ("view", "layout"):
            return cls.COMPOSITION
        return None

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        result = handler(schema)
        result["enum"] = list(dict.fromkeys(role.value for role in cls))
        return result


class JobStatus(StrEnum):
    """job 상태 7종 (완료·실패만 종결 상태)."""

    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    SEARCHING = "searching"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStatus(StrEnum):
    """레퍼런스·기록 회상·그림 대화의 최종 결과 상태."""

    SUCCESS = "success"
    NEEDS_CLARIFICATION = "needs_clarification"
    OUT_OF_SCOPE = "out_of_scope"
    UNSAFE_INPUT = "unsafe_input"
    PARTIAL_RESULT = "partial_result"
    MEMORY_ANSWER = "memory_answer"
    REFERENCE_GUIDANCE = "reference_guidance"
    DRAWING_CHAT = "drawing_chat"


class ReasonCode(StrEnum):
    """AGentResult·TermResult의 사유 코드 8종."""

    ABSTRACT_INTENT_ONLY = "ABSTRACT_INTENT_ONLY"
    INSUFFICIENT_VISUAL_EVIDENCE = "INSUFFICIENT_VISUAL_EVIDENCE"
    CONFLICTING_CONSTRAINTS = "CONFLICTING_CONSTRAINTS"
    DIRECT_SEARCH_DISABLED = "DIRECT_SEARCH_DISABLED"
    PIN_RESULTS_EMPTY = "PIN_RESULTS_EMPTY"
    PIN_SEARCH_UNAVAILABLE = "PIN_SEARCH_UNAVAILABLE"
    OUT_OF_SCOPE_REQUEST = "OUT_OF_SCOPE_REQUEST"
    UNSAFE_INPUT = "UNSAFE_INPUT"
    CATALOG_LIMITATION = "CATALOG_LIMITATION"
    CLARIFICATION_REPEATED = "CLARIFICATION_REPEATED"


class FailureCode(StrEnum):
    """최종 실패 코드 13종.

    - LLM_*·SEARCH_*·JOB_INSTANCE_INTERRUPTED: 회복 가능 -> 자동 재시도 3회
    - CONFIGURATION_ERROR·DATABASE_*·CATALOG_INVALID_AT_STARTUP·INTERNAL_CODE_ERROR: 즉시 실패
    """

    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_UPSTREAM_UNAVAILABLE = "LLM_UPSTREAM_UNAVAILABLE"
    LLM_INVALID_STRUCTURED_OUTPUT = "LLM_INVALID_STRUCTURED_OUTPUT"
    SEARCH_TIMEOUT = "SEARCH_TIMEOUT"
    SEARCH_RATE_LIMITED = "SEARCH_RATE_LIMITED"
    SEARCH_UPSTREAM_UNAVAILABLE = "SEARCH_UPSTREAM_UNAVAILABLE"
    JOB_INSTANCE_INTERRUPTED = "JOB_INSTANCE_INTERRUPTED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DATABASE_MIGRATION_ERROR = "DATABASE_MIGRATION_ERROR"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    CATALOG_INVALID_AT_STARTUP = "CATALOG_INVALID_AT_STARTUP"
    INTERNAL_CODE_ERROR = "INTERNAL_CODE_ERROR"


class ApiErrorCode(StrEnum):
    """Request-stage HTTP errors; keep aligned with ``api-contract.md``.

    These are separate from terminal worker ``FailureCode`` values. The set
    includes session lookup and the server-authoritative message-limit error.
    """

    INVALID_REQUEST_TEXT = "invalid_request_text"
    IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
    SESSION_REQUIRED = "session_required"
    JOB_NOT_FOUND = "job_not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_MESSAGE_LIMIT_REACHED = "session_message_limit_reached"


class PinStatus(StrEnum):
    """Pin 상태 2종."""

    AVAILABLE = "available"
    DELETED = "deleted"
    UNAVAILABLE = "unavailable"


class InterpretationState(StrEnum):
    """카드 해석, 문맥 질문 또는 일반 그림 대화."""

    SELECT_TERMS = "select_terms"
    NEEDS_CLARIFICATION = "needs_clarification"

    DRAWING_CHAT = "drawing_chat"


class ClarificationType(StrEnum):
    """needs_clarification 상태에서 LLM이 후보로 제시하는 모호성 유형.

    최종 agent_status·reason_codes는 resolver가 검증 후 조립한다. DIRECT_SEARCH_DISABLED는
    LLM 후보가 아닌 resolver 전용이다.
    """

    ABSTRACT_INTENT = "abstract_intent"
    INSUFFICIENT_VISUAL_EVIDENCE = "insufficient_visual_evidence"
    CONFLICTING_CONSTRAINTS = "conflicting_constraints"
    CATALOG_LIMITATION = "catalog_limitation"
