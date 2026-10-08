"""공개 API 계약 모델 (docs/specs/api-contract.md 기준).

모든 모델은 `extra="forbid"`로 허용되지 않은 필드를 거부한다.
상태 간 불변 조건(job 상태별 null 규칙, agent_status별 사유 코드 규칙)을 검증기로 강제한다.
"""

from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.schemas.memory import ContextUpdate, MemorySource, NO_RECORDS, TOO_MANY

from backend.schemas.enums import (
    AgentStatus,
    ApiErrorCode,
    ClarificationType,
    FailureCode,
    InterpretationState,
    JobStatus,
    PinStatus,
    ReasonCode,
    Role,
)

MAX_PINS_PER_ROLE = 8
RETRY_COUNT_MAX = 3
PROGRESS_POLL_AFTER_MS = 1000


class AgentRequest(BaseModel):
    """POST /api/agent 요청 — request_text 1~500자와 선택적 대화 UUID를 허용."""

    model_config = ConfigDict(extra="forbid")

    request_text: Annotated[str, Field(min_length=1, max_length=500)]
    session_id: UUID | None = None

    @model_validator(mode="after")
    def _reject_whitespace_only(self) -> "AgentRequest":
        if not self.request_text.strip():
            raise ValueError("request_text는 공백만으로 이루어질 수 없다")
        return self


class SubmissionResponse(BaseModel):
    """POST /api/agent 202 응답 본문 (HttpOnly cookie는 별도로 설정)."""

    job_id: str
    job_status: Literal[JobStatus.QUEUED] = JobStatus.QUEUED
    poll_after_ms: int = PROGRESS_POLL_AFTER_MS


class PinResult(BaseModel):
    """역할 검색 결과의 Pin 하나. 원본 pin_url과 응답 전용 thumbnail_url만 가진다."""

    model_config = ConfigDict(extra="forbid")

    pin_id: str
    pin_url: str
    thumbnail_url: str | None = None
    status: PinStatus

    @model_validator(mode="after")
    def _deleted_pin_has_no_thumbnail(self) -> "PinResult":
        if self.status is PinStatus.DELETED and self.thumbnail_url is not None:
            raise ValueError("deleted Pin은 thumbnail_url=null이어야 한다")
        return self


class TermResult(BaseModel):
    """역할당 최대 하나의 활성 TERM_CARD 결과."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    term_id: str
    label_ko: str
    label_en: str
    plain_meaning_ko: str
    selection_reason: str | None = None
    reference_checkpoints: list[str] = Field(default_factory=list)
    search_url: str
    pins: Annotated[list[PinResult], Field(max_length=MAX_PINS_PER_ROLE)] = Field(
        default_factory=list
    )
    reason_codes: list[ReasonCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_reason_codes(self) -> "TermResult":
        allowed: set[ReasonCode] = {ReasonCode.PIN_RESULTS_EMPTY, ReasonCode.PIN_SEARCH_UNAVAILABLE}
        if not set(self.reason_codes) <= allowed:
            raise ValueError(
                "TermResult.reason_codes는 빈 배열, PIN_RESULTS_EMPTY, PIN_SEARCH_UNAVAILABLE 중 하나만 허용된다"
            )
        if len(self.reason_codes) > 1:
            raise ValueError("TermResult.reason_codes는 최대 하나의 코드만 가진다")
        return self


class ReferencePlan(BaseModel):
    """검증된 참조 계획 — 역할당 최대 하나의 활성 카드를 역할 순서대로."""

    model_config = ConfigDict(extra="forbid")

    terms: list[TermResult] = Field(default_factory=list)
    unresolved_roles: list[Role] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_role_uniqueness_and_order(self) -> "ReferencePlan":
        seen: set[Role] = set()
        prev_index = -1
        for term in self.terms:
            if term.role in seen:
                raise ValueError(f"역할당 최대 하나의 TERM_CARD만 가진다: role={term.role}")
            seen.add(term.role)
            role_index = list(Role).index(term.role)
            if role_index < prev_index:
                raise ValueError("terms는 역할 순서(body→pose→view→perspective→layout)를 지켜야 한다")
            prev_index = role_index
        for role in self.unresolved_roles:
            if role in seen:
                raise ValueError(f"unresolved_roles에 있는 역할은 terms와 겹칠 수 없다: role={role}")
        return self


class ReferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replaced_roles: list[Role] = Field(default_factory=list, max_length=5)
    preserved_roles: list[Role] = Field(default_factory=list, max_length=5)
    removed_roles: list[Role] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def disjoint_roles(self):
        roles = self.replaced_roles + self.preserved_roles + self.removed_roles
        if len(roles) != len(set(roles)):
            raise ValueError("reference update roles must be unique and disjoint")
        return self


class AgentResult(BaseModel):
    """API 응답 결과 — 서버가 조립한 최종 상태.

    상태별 불변 규칙:
    - success: reason_codes 빈 배열, reference_plan 필수
    - partial_result: reason_codes는 PIN_RESULTS_EMPTY/PIN_SEARCH_UNAVAILABLE만, reference_plan 필수
    - needs_clarification: reference_plan=null, 비어 있지 않은 clarifying_question 필수
    - out_of_scope: reference_plan=null, clarifying_question=null, reason_codes=[OUT_OF_SCOPE_REQUEST]
    - unsafe_input: reference_plan=null, clarifying_question=null, reason_codes=[UNSAFE_INPUT]
    """

    model_config = ConfigDict(extra="forbid")

    agent_status: AgentStatus
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    reference_plan: ReferencePlan | None = None
    reference_update: ReferenceUpdate | None = None
    clarifying_question: str | None = None
    user_message: str = ""
    answer_text: Annotated[str, Field(strict=True, max_length=4000)] = ""
    memory_answer: str | None = Field(default=None, min_length=1, max_length=2000)
    sources: list[MemorySource] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _validate_state_rules(self) -> "AgentResult":
        codes = set(self.reason_codes)
        if update := self.reference_update:
            if self.agent_status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL_RESULT):
                final = {term.role for term in self.reference_plan.terms} if self.reference_plan else set()
                if final != set(update.replaced_roles + update.preserved_roles):
                    raise ValueError("reference update must cover the final board")
            elif self.agent_status is AgentStatus.NEEDS_CLARIFICATION:
                if update.replaced_roles or update.removed_roles:
                    raise ValueError("clarification cannot replace or remove references")
            else:
                raise ValueError("reference update requires a board result or clarification")
        if self.memory_answer and not self.sources and self.memory_answer not in (NO_RECORDS, TOO_MANY):
            raise ValueError("a factual memory answer requires original sources")
        if self.sources and not self.memory_answer:
            raise ValueError("sources require a memory answer")
        if self.agent_status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL_RESULT):
            if self.reference_plan is None:
                raise ValueError("success·partial_result는 reference_plan이 필수다")
            if self.clarifying_question is not None:
                raise ValueError("success·partial_result는 clarifying_question이 없어야 한다")
            if self.agent_status is AgentStatus.SUCCESS:
                if codes:
                    raise ValueError("success의 reason_codes는 빈 배열만 허용된다")
            else:
                if not codes <= {ReasonCode.PIN_RESULTS_EMPTY, ReasonCode.PIN_SEARCH_UNAVAILABLE}:
                    raise ValueError(
                        "partial_result의 reason_codes는 PIN_RESULTS_EMPTY/PIN_SEARCH_UNAVAILABLE만 허용된다"
                    )
        elif self.agent_status is AgentStatus.NEEDS_CLARIFICATION:
            if self.reference_plan is not None:
                raise ValueError("needs_clarification은 reference_plan=null이어야 한다")
            if not self.clarifying_question or not self.clarifying_question.strip():
                raise ValueError("needs_clarification은 비어 있지 않은 clarifying_question이 필수다")
            if not codes <= {
                ReasonCode.ABSTRACT_INTENT_ONLY,
                ReasonCode.INSUFFICIENT_VISUAL_EVIDENCE,
                ReasonCode.CONFLICTING_CONSTRAINTS,
                ReasonCode.DIRECT_SEARCH_DISABLED,
            }:
                raise ValueError(
                    "needs_clarification의 reason_codes는 4종 clarified 코드 중에서만 가능하다"
                )
            if not codes:
                raise ValueError("needs_clarification은 reason_codes가 최소 하나 있어야 한다")
        elif self.agent_status is AgentStatus.MEMORY_ANSWER:
            if not self.memory_answer or self.reference_plan or self.reason_codes or self.clarifying_question:
                raise ValueError("memory_answer requires text and forbids reference plan")
        else:  # OUT_OF_SCOPE, UNSAFE_INPUT
            if self.reference_plan is not None:
                raise ValueError(f"{self.agent_status}는 reference_plan=null이어야 한다")
            if self.clarifying_question is not None:
                raise ValueError(f"{self.agent_status}는 clarifying_question=null이어야 한다")
            expected = (
                ReasonCode.OUT_OF_SCOPE_REQUEST
                if self.agent_status is AgentStatus.OUT_OF_SCOPE
                else ReasonCode.UNSAFE_INPUT
            )
            if codes != {expected}:
                raise ValueError(f"{self.agent_status}의 reason_codes는 [{expected}]만 허용된다")

        if len(codes) != len(self.reason_codes):
            raise ValueError("reason_codes 배열은 중복을 허용하지 않는다")
        return self


class Failure(BaseModel):
    """최종 실패 — result=null과 함께 반환된다. 재시도하지 않는다."""

    model_config = ConfigDict(extra="forbid")

    failure_code: FailureCode
    user_message: str
    retryable: Literal[False] = False


class ApiError(BaseModel):
    """HTTP 오류 응답 본문 — `Failure`와 같은 형태, 코드 네임스페이스만 다르다.

    `Failure.failure_code`는 job 종결 실패 전용 13종이고, 요청 단계에서 거부되는
    코드는 `ApiErrorCode` 4종이다. 본문 형태를 통일해 프론트가 한 가지 모양으로
    오류를 다루게 한다.
    """

    model_config = ConfigDict(extra="forbid")

    failure_code: ApiErrorCode
    user_message: str
    retryable: Literal[False] = False


class JobEnvelope(BaseModel):
    """GET /api/jobs/{job_id} 응답.

    - 진행 중: result=null, failure=null, poll_after_ms=1000
    - completed: result 필수, failure=null, poll_after_ms=null
    - failed: result=null, failure 필수, poll_after_ms=null
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    session_id: str
    job_status: JobStatus
    attempt: Annotated[int, Field(ge=1)]
    max_attempts: Annotated[int, Field(ge=1, le=RETRY_COUNT_MAX)]
    poll_after_ms: int | None = None
    result: AgentResult | None = None
    failure: Failure | None = None

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> "JobEnvelope":
        if self.attempt > self.max_attempts:
            raise ValueError("attempt는 max_attempts보다 클 수 없다")
        if self.job_status in (JobStatus.COMPLETED, JobStatus.FAILED):
            if self.poll_after_ms is not None:
                raise ValueError("종결 상태는 poll_after_ms=null이어야 한다")
            if self.job_status is JobStatus.COMPLETED:
                if self.result is None:
                    raise ValueError("completed는 result가 필수다")
                if self.failure is not None:
                    raise ValueError("completed는 failure=null이어야 한다")
            else:
                if self.result is not None:
                    raise ValueError("failed는 result=null이어야 한다")
                if self.failure is None:
                    raise ValueError("failed는 failure가 필수다")
        else:
            if self.result is not None:
                raise ValueError("진행 상태는 result=null이어야 한다")
            if self.failure is not None:
                raise ValueError("진행 상태는 failure=null이어야 한다")
            if self.poll_after_ms != PROGRESS_POLL_AFTER_MS:
                raise ValueError(f"진행 상태는 poll_after_ms={PROGRESS_POLL_AFTER_MS}이어야 한다")
        return self


class InterpretationSelection(BaseModel):
    """LLM 해석이 제안하는 역할·용어 선택 (LLM은 최종 선택을 확정하지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    term_id: str
    evidence: Annotated[list[str], Field(min_length=1)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    source_job_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_evidence(self) -> "InterpretationSelection":
        for phrase in self.evidence:
            if not phrase or not phrase.strip():
                raise ValueError("evidence 항목은 비어 있거나 공백만으로 이루어질 수 없다")
        return self


class InterpretationOutput(BaseModel):
    """LLM adapter의 유일한 반환 구조 (api-contract.md §How, prompt-interpreter-v0.md).

    LLM은 agent_status, reason_codes, 검색 URL을 만들지 않는다.

    상태별 불변 규칙:
    - select_terms: selections 1개 이상·역할 중복 없음·순서 준수, unresolved_constraints=[],
      clarifying_question=null, clarification_type=null
    - needs_clarification: selections=[], unresolved_constraints 1개 이상,
      비어 있지 않은 clarifying_question 필수, clarification_type 필수
    """

    model_config = ConfigDict(extra="forbid")

    interpretation_state: InterpretationState
    selections: list[InterpretationSelection] = Field(default_factory=list)
    unresolved_constraints: list[str] = Field(default_factory=list)
    clarifying_question: str | None = None
    clarification_type: ClarificationType | None = None
    context_updates: list[ContextUpdate] = Field(default_factory=list, max_length=5)
    answer_text: Annotated[str, Field(strict=True, max_length=4000)] = ""

    @model_validator(mode="after")
    def _validate_unresolved_constraints(self) -> "InterpretationOutput":
        for constraint in self.unresolved_constraints:
            if not constraint or not constraint.strip():
                raise ValueError("unresolved_constraints 항목은 비어 있거나 공백만으로 이루어질 수 없다")
        return self

    @model_validator(mode="after")
    def _validate_state_rules(self) -> "InterpretationOutput":
        if self.interpretation_state is InterpretationState.SELECT_TERMS:
            if not self.selections:
                raise ValueError("select_terms는 selections가 최소 하나 있어야 한다")
            seen: set[Role] = set()
            prev_index = -1
            for selection in self.selections:
                if selection.role in seen:
                    raise ValueError(f"역할당 최대 하나의 selection만 가진다: role={selection.role}")
                seen.add(selection.role)
                role_index = list(Role).index(selection.role)
                if role_index < prev_index:
                    raise ValueError(
                        "selections는 역할 순서(body→pose→view→perspective→layout)를 지켜야 한다"
                    )
                prev_index = role_index
            if self.unresolved_constraints:
                raise ValueError("select_terms는 unresolved_constraints=[]이어야 한다")
            if self.clarifying_question is not None:
                raise ValueError("select_terms는 clarifying_question=null이어야 한다")
            if self.clarification_type is not None:
                raise ValueError("select_terms는 clarification_type=null이어야 한다")
        elif self.interpretation_state is InterpretationState.NEEDS_CLARIFICATION:
            if self.selections:
                raise ValueError("needs_clarification는 selections=[]이어야 한다")
            if not self.unresolved_constraints:
                raise ValueError("needs_clarification는 unresolved_constraints가 최소 하나 있어야 한다")
            if not self.clarifying_question or not self.clarifying_question.strip():
                raise ValueError("needs_clarification는 비어 있지 않은 clarifying_question이 필수다")
            if self.clarification_type is None:
                raise ValueError("needs_clarification는 clarification_type이 필수다")
        return self
