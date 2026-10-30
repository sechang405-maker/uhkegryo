"""Execute claimed jobs through the LLM, resolver, and response assembler."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Mapping

from backend.schemas.enums import AgentStatus, FailureCode, JobStatus, ReasonCode, Role
from backend.schemas.models import AgentResult, InterpretationOutput
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.conversation_memory import ConversationMemory
from backend.services import conversation_context
from backend.services import reference_update
from backend.services import recommendations
from backend.services.reference_intent import (
    PERSONAL_TERM_CREATION_GUIDANCE,
    explicit_non_search,
    requests_personal_term_creation,
)
from backend.services.input_safety import is_out_of_scope_input, is_unsafe_input
from backend.services.job_repository import JobRepository, StaleJobAttempt
from backend.services.job_retry_recovery import JobRetryRecovery
from backend.services.job_trace import AttemptTrace, JobTracer
from backend.services.llm import (
    AgentInterpretationAdapter,
    LLMInterpretationAdapter,
    LLMInvalidStructuredOutput,
)
from backend.services.llm import format_active_cards_json
from backend.services.ollama_grounded import OllamaGroundedInterpreter
from backend.services.mcp_pinterest_search import parse_search_result, pop_search_diagnostics
from backend.services.mcp_tool_gateway import McpToolGateway
from backend.services.pinterest_widget import PinterestWidgetClient
from backend.services.personal_catalog import with_personal_terms
from backend.services.personal_term_repository import PersonalTermRepository
from backend.services.quota_repository import QuotaRepository
from backend.services.searxng_pinterest_search import SearXNGPinterestSearchProvider
from backend.services.resolver import ResolutionResult
from backend.services.response_assembler import OUT_OF_SCOPE_MESSAGE, RoleSearchOutcome, assemble
from backend.services.failure_mapping import DATABASE_ERRORS, OperationalFailure, classify_failure

logger = logging.getLogger(__name__)
WORKER_CONCURRENCY = 5
POLL_INTERVAL_SECONDS = 1
SEARCH_RETRY_DELAYS_SECONDS = (1, 2)
SEARCH_CONCURRENCY = 3
LOCAL_SEARCH_IO_TIMEOUT_SECONDS = 25
LOCAL_SEARCH_TOTAL_TIMEOUT_SECONDS = 110
MAX_MCP_TOOL_CALLS = 16
PINTEREST_SEARCH_TOOL = "search_pinterest_pins"
MCP_TOOL_REFRESH_INTERVAL_SECONDS = 3 * 60 * 60
MCP_TOOL_REFRESH_TIMEOUT_SECONDS = 30


class AgentJobWorker:
    """Claim and execute one job; retry and lease policy stays in JobRetryRecovery."""

    def __init__(
        self,
        pool: Any,
        snapshot: CatalogSnapshot,
        *,
        adapter: AgentInterpretationAdapter | None = None,
        mcp_gateway: McpToolGateway | None = None,
        widget_client: PinterestWidgetClient | None = None,
        search_json_loader=None,
        local_search_url: str = '',
        heartbeat_interval: float = 10,
        tracer: JobTracer | None = None,
        personal_terms: PersonalTermRepository | None = None,
        llm_call_reserver: Callable[[], Awaitable[int]] | None = None,
        grounded_ollama: bool = False,
    ) -> None:
        self._pool = pool
        self._jobs = JobRepository(pool)
        self._memory = ConversationMemory(pool)
        self._recovery = JobRetryRecovery(pool)
        self._snapshot = snapshot
        self._adapter = adapter
        self._mcp_gateway = mcp_gateway
        self._widget_client = widget_client
        self._search_json_loader = search_json_loader
        self._local_search_url = local_search_url
        self._search_slots = asyncio.Semaphore(SEARCH_CONCURRENCY)
        self._heartbeat_interval = heartbeat_interval
        self._tracer = tracer if tracer is not None else JobTracer.from_settings()
        self._personal_terms = personal_terms
        self._llm_call_reserver = llm_call_reserver
        self._grounded_ollama = grounded_ollama

    async def run_once(
        self,
        *,
        search_outcomes: Mapping[str | Role, RoleSearchOutcome] | None = None,
    ) -> bool:
        job = await self._jobs.claim_next()
        if job is None:
            return False
        with self._tracer.attempt(job) as trace:
            try:
                await self._with_heartbeat(job, self._process_claimed(job, search_outcomes, trace))
            except StaleJobAttempt:
                trace.stale()
            except Exception as error:
                trace.failed(job, error)
                raise
        return True

    async def _process_claimed(
        self, job: Any, search_outcomes: Mapping | None, trace: AttemptTrace
    ) -> None:
        job_id, attempt = str(job["job_id"]), job["attempt"]
        try:
            if not await self._update(job_id, attempt, JobStatus.VALIDATING):
                trace.stale()
                return
            if is_unsafe_input(str(job["request_text"])):
                result = AgentResult(
                    agent_status=AgentStatus.UNSAFE_INPUT,
                    reason_codes=[ReasonCode.UNSAFE_INPUT],
                    reference_plan=None,
                    clarifying_question=None,
                    user_message=(
                        "요청하신 내용은 지원할 수 없습니다. "
                        "캐릭터의 체형·포즈·시점을 텍스트로 설명해 주세요."
                    ),
                )
                if await self._update(job_id, attempt, JobStatus.COMPLETED, result=result):
                    trace.completed(result)
                else:
                    trace.stale()
                return
            if is_out_of_scope_input(str(job["request_text"])):
                result = AgentResult(
                    agent_status=AgentStatus.OUT_OF_SCOPE,
                    reason_codes=[ReasonCode.OUT_OF_SCOPE_REQUEST],
                    reference_plan=None,
                    clarifying_question=None,
                    user_message=OUT_OF_SCOPE_MESSAGE,
                )
                if await self._update(job_id, attempt, JobStatus.COMPLETED, result=result):
                    trace.completed(result)
                else:
                    trace.stale()
                return
            snapshot = self._snapshot
            if self._personal_terms is not None:
                snapshot = with_personal_terms(
                    snapshot,
                    await self._personal_terms.list_active_terms_for_session(str(job["session_id"])),
                )
            if requests_personal_term_creation(job["request_text"]):
                with trace.stage("memory-context"):
                    context = await conversation_context.prepare(self._memory, job, None, trace)
                    recommendations.reset_context(job, context)
                result = AgentResult(
                    agent_status=AgentStatus.REFERENCE_GUIDANCE,
                    reason_codes=[ReasonCode.CATALOG_LIMITATION],
                    reference_plan=None,
                    clarifying_question=None,
                    user_message=PERSONAL_TERM_CREATION_GUIDANCE,
                )
                with trace.stage("rendering"):
                    if not await self._update(job_id, attempt, JobStatus.RENDERING):
                        trace.stale()
                        return
                    with self._tracer.phase("conversation-state-update") as metrics:
                        state = conversation_context.next_state(
                            context, job, None, result, snapshot=snapshot
                        )
                        state = recommendations.next_state(state, job, None)
                        await self._memory.complete(job, result, state)
                        metrics.update(state_saved=True)
                trace.completed(result)
                return
            if self._adapter is None:
                from backend.shared.config import get_settings
                if get_settings().llm_backend == 'codex-cli':
                    from backend.services.codex_llm import CodexInterpretationAdapter
                    self._adapter = CodexInterpretationAdapter()
                else:
                    self._adapter = LLMInterpretationAdapter(
                        call_reserver=self._llm_call_reserver
                    )
            with trace.stage("memory-context"):
                context = await conversation_context.prepare(self._memory, job, self._adapter, trace)
                recommendations.reset_context(job, context)
            recommendation_intent = recommendations.has_intent(job, context)
            recommendation_decision = None
            feedback = job.get("validation_feedback_json")
            if isinstance(feedback, str):
                feedback = json.loads(feedback)
            routed = None
            combined = getattr(self._adapter, "route_and_interpret", None)
            if callable(combined) and not recommendation_intent and not conversation_context.is_clear_new_request(job["request_text"], context):
                terms = ((context.get("previous_result") or {}).get("reference_plan") or {}).get("terms", [])
                routed = await combined(job["request_text"], **conversation_context.trace_args(job),
                    active_cards_json=format_active_cards_json(snapshot),
                    session_context=conversation_context.prompt_context(context),
                    current_reference_terms=[{key: term[key] for key in ("role", "term_id", "label_ko", "label_en")} for term in terms],
                    current_reference_roles=[term["role"] for term in terms],
                    **({"validation_feedback": feedback} if feedback else {}))
            if recommendation_intent:
                recalled, recall_only = None, False
            else:
                recalled, recall_only = await conversation_context.recall(
                    self._memory, job, context, self._adapter, trace,
                    **({"query": routed.route} if routed is not None else {}))
            state = context["state"]
            if recall_only:
                result = recalled
            else:
                previous = reference_update.previous_terms(context, snapshot)
                refresh = context.get("reference_action") in ("refresh_all", "refresh_roles", "refresh_terms")
                interpretation = None
                grounded_queries: dict[str, tuple[str, ...]] = {}
                with trace.stage("validating"):
                    if refresh:
                        resolution = reference_update.refresh_resolution(previous, snapshot, context)
                    else:
                        interpretation = routed.interpretation if routed is not None else None
                        if interpretation is None:
                            if self._grounded_ollama:
                                grounded = await OllamaGroundedInterpreter(
                                    snapshot, self._adapter
                                ).interpret_grounded(
                                    job["request_text"],
                                    **conversation_context.trace_args(job),
                                )
                                interpretation = grounded.interpretation
                                grounded_queries = grounded.query_fragments_by_term
                            else:
                                interpretation = await self._adapter.interpret(
                                    job["request_text"], **conversation_context.trace_args(job),
                                    active_cards_json=format_active_cards_json(snapshot),
                                    session_context=conversation_context.prompt_context(context),
                                    **({"validation_feedback": feedback} if feedback else {}),
                                )
                        if requests_personal_term_creation(job["request_text"]):
                            interpretation = InterpretationOutput(
                                interpretation_state="needs_clarification",
                                answer_text=PERSONAL_TERM_CREATION_GUIDANCE,
                                unresolved_constraints=["개인 용어 생성 화면 미연결"],
                                clarifying_question=PERSONAL_TERM_CREATION_GUIDANCE,
                                clarification_type="catalog_limitation",
                            )
                        if interpretation.interpretation_state == 'select_terms' and explicit_non_search(job['request_text']):
                            raise LLMInvalidStructuredOutput('Explicit non-search intent conflicts with selected reference terms',
                                stage='conversation_validation', feedback=[{'path': [], 'code': 'reference_intent_conflict'}])
                        recommendation_decision = await recommendations.handle(
                            self._memory, job, interpretation, snapshot, context)
                        if context.get('_recommendation_topic_reset'):
                            previous = {}
                        if recommendation_decision:
                            interpretation = recommendation_decision.interpretation
                            resolution = recommendation_decision.resolution
                            # A newly adopted candidate defines its own search board.
                            if recommendation_decision.adoption:
                                previous = {}
                        else:
                            interpretation = await conversation_context.reference_fallback(
                                self._memory, job, interpretation, snapshot, context)
                            resolution = await conversation_context.validate(
                                self._memory, job, interpretation, snapshot, context=context)
                            resolution = reference_update.select_searches(resolution, previous)
                if recommendation_decision and recommendation_decision.result:
                    result = recommendation_decision.result
                elif resolution.status in ('chat', 'out_of_scope'):
                    result = assemble(resolution, snapshot, answer_text=interpretation.answer_text)
                else:
                    with trace.stage("searching"):
                        with self._tracer.phase("search-status-update"):
                            if not await self._update(job_id, attempt, JobStatus.SEARCHING):
                                trace.stale()
                                return
                        if search_outcomes is None:
                            search_outcomes = await self._search_outcomes(
                                resolution, request_text=str(job["request_text"]),
                                query_fragments_by_term=grounded_queries,
                                **({"exclude_pin_ids": {term_id: list(dict.fromkeys(
                                    pin.pin_id for pin in term.pins))
                                    for term_id, term in previous.items()}} if refresh else {}),
                            )
                    with self._tracer.phase("search-result-assembly") as metrics:
                        result = assemble(resolution, snapshot, search_outcomes,
                            answer_text=("기존 조건을 유지하고 요청한 카드의 레퍼런스만 다시 찾았어요."
                                if context.get("reference_action") == "refresh_terms"
                                else "기존 조건은 유지하고 요청한 역할의 레퍼런스를 다시 찾았어요."
                                if context.get("reference_action") == "refresh_roles"
                                else "기존 조건은 유지하고 전체 레퍼런스를 다시 찾았어요.") if refresh else interpretation.answer_text)
                        if refresh and result.reference_plan is not None and result.reason_codes:
                            result.answer_text = "기존 조건은 유지했지만 일부 새 레퍼런스를 찾지 못했어요. 검색 결과 안내를 확인해 주세요."
                        result = reference_update.merge_preserved(result, previous, interpretation)
                        result = reference_update.annotate(result, context, [term.selection.term_id for term in resolution.terms])
                        metrics.update(
                            role_count=len(search_outcomes),
                            pin_count=sum(len(outcome.pins) for outcome in search_outcomes.values()),
                        )
                result = recommendations.finish(result, recommendation_decision)
                if context.get('_recommendation_topic_reset'):
                    result.context_reset = True
                if recalled is not None:
                    result.memory_answer, result.sources = recalled.memory_answer, recalled.sources
            with trace.stage("rendering"):
                if not await self._update(job_id, attempt, JobStatus.RENDERING):
                    trace.stale()
                    return
                with self._tracer.phase("conversation-state-update") as metrics:
                    if not recall_only and not refresh:
                        state = conversation_context.next_state(context, job, interpretation, result, snapshot=snapshot)
                        state = recommendations.next_state(state, job, recommendation_decision)
                    await self._memory.complete(job, result, state)
                    metrics.update(state_saved=True)
            trace.completed(result)
        except StaleJobAttempt:
            trace.stale()
        except Exception as error:
            if isinstance(error, LLMInvalidStructuredOutput) and self._adapter is not None:
                record = getattr(self._adapter, "record_validation_failure", None)
                if callable(record):
                    try:
                        record(error, attempt=job["attempt"])
                    except Exception as diagnostic_error:
                        logger.debug("validation diagnostic recording failed",
                                     extra={"error_type": type(diagnostic_error).__name__})
            await self._handle_failure(job, error, trace)

    async def _search_outcomes(
        self, resolution: ResolutionResult, *, request_text: str, exclude_pin_ids=None,
        query_fragments_by_term: Mapping[str, tuple[str, ...]] | None = None,
    ) -> Mapping[str | Role, RoleSearchOutcome]:
        excluded_board_pins = {pin_id for pins in (exclude_pin_ids or {}).values() for pin_id in pins}
        if getattr(self, '_local_search_url', ''):
            return await self._local_search_outcomes(
                resolution, exclude_pin_ids or {}, query_fragments_by_term or {}
            )
        if not getattr(self._adapter, 'image_search_enabled', True):
            return {term.selection.term_id: RoleSearchOutcome(role=term.selection.role,
                code=ReasonCode.PIN_SEARCH_UNAVAILABLE) for term in resolution.terms}
        if self._mcp_gateway is None or not resolution.terms:
            return {}
        adapter = self._adapter
        if not hasattr(adapter, "request_mcp_tool_calls"):
            raise ValueError("해석 어댑터가 MCP tool calling을 지원하지 않습니다")
        with self._tracer.phase("mcp-tools-list"):
            tools = await self._mcp_gateway.list_tools()
        approved = self._approved_query_fragments(
            resolution, query_fragments_by_term or {}
        )
        roles = {term.selection.term_id: term.selection.role for term in resolution.terms}
        # term_id belongs to orchestration; the provider transport still takes role/fragments.
        tools = deepcopy(tools)
        for tool in tools:
            if tool['name'] == PINTEREST_SEARCH_TOOL:
                schema = tool['inputSchema']
                schema.setdefault('properties', {})['term_id'] = {'type': 'string', 'enum': list(approved)}
                schema['required'] = list(dict.fromkeys([*schema.get('required', []), 'term_id']))
        outcomes: dict[str, RoleSearchOutcome] = {}
        attempts: dict[str, int] = {term_id: 0 for term_id in approved}
        tool_call_count = 0
        messages = [
            {"role": "system", "content": (
                "Use the registered MCP tools to fulfill the request. For Pinterest searches, "
                "call search_pinterest_pins only with an approved term_id, its role, and its exact "
                "query_fragments. Never invent or alter fragments. Use other listed tools "
                "when needed. Select independent searches for all unfinished approved term IDs "
                "together in one response, at most once per term ID. After tool results, retry "
                "only unfinished term IDs; do not search completed term IDs again. "
                "After a tool result, decide whether another tool call is needed."
            )},
            {"role": "user", "content": json.dumps({
                "request": request_text,
                "approved_terms": [
                    {
                        "role": term.selection.role.value,
                        "term_id": term.selection.term_id,
                        "query_fragments": list(term.card["query_fragments"]),
                    }
                    for term in resolution.terms
                ],
            }, ensure_ascii=False)},
        ]
        for call_round in range(1, MAX_MCP_TOOL_CALLS + 1):
            pending = [role for role in approved if role not in outcomes]
            purpose = "tool_selection" if pending else "post_search_decision"
            with self._tracer.phase(
                "mcp-tool-selection" if pending else "mcp-post-search-decision",
                call_round=call_round, purpose=purpose, pending_term_ids=pending,
            ) as metrics:
                calls = await adapter.request_mcp_tool_calls(messages, tools, required=bool(pending))
                metrics.update(call_count=len(calls), selected_roles=sorted({
                    call["arguments"].get("role") for call in calls
                    if call["name"] == PINTEREST_SEARCH_TOOL
                    and isinstance(call["arguments"].get("role"), str)
                    and call["arguments"].get("role") in {role.value for role in roles.values()}
                }))
            if not calls:
                break
            assistant_calls = []
            for call in calls:
                name, arguments, call_id = call["name"], call["arguments"], call["id"]
                assistant_calls.append({
                    "id": call_id, "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                })
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_calls})
            batch_terms: set[str] = set()

            async def execute(call):
                nonlocal tool_call_count
                name, arguments, call_id = call["name"], call["arguments"], call["id"]
                if tool_call_count >= MAX_MCP_TOOL_CALLS:
                    return {
                        "role": "tool", "tool_call_id": call_id,
                        "content": json.dumps({"error": "MCP tool-call limit reached"}),
                    }
                tool_call_count += 1
                result: dict
                search_attempted = False
                role = None
                term_id = None
                try:
                    if name == PINTEREST_SEARCH_TOOL:
                        role = Role(arguments.get("role"))
                        term_id = arguments.get("term_id")
                        if term_id is None:
                            matches = [key for key, value in roles.items() if value == role]
                            term_id = matches[0] if len(matches) == 1 else None
                        fragments = arguments.get("query_fragments")
                        if term_id not in approved or term_id in outcomes or roles[term_id] != role:
                            raise ValueError("Pinterest search arguments are outside approved terms")
                        if fragments != list(approved[term_id]):
                            raise ValueError("Pinterest search arguments are outside approved terms")
                        if term_id in batch_terms:
                            raise ValueError("Duplicate Pinterest term in one response")
                        if attempts[term_id] >= 3:
                            raise ValueError("Pinterest search retry limit exceeded")
                        batch_terms.add(term_id)
                        attempts[term_id] += 1
                        search_attempted = True
                    if search_attempted:
                        trace_fields = {"role": role.value, "term_id": term_id, "search_attempt": attempts[term_id]}
                        with self._tracer.phase("search-slot-wait", **trace_fields):
                            await self._search_slots.acquire()
                        try:
                            with self._tracer.search(role.value, list(approved[term_id]),
                                                     search_attempt=attempts[term_id]) as search_span:
                                with self._tracer.phase("mcp-search-call", **trace_fields):
                                    actual_arguments = {"role": role.value, "query_fragments": list(approved[term_id])}
                                    excluded = (exclude_pin_ids or {}).get(term_id, [])
                                    if excluded:
                                        actual_arguments["exclude_pin_ids"] = excluded
                                    result = await self._mcp_gateway.call_tool(name, actual_arguments)
                                diagnostics = pop_search_diagnostics(result)
                                self._tracer.search_result(search_span, diagnostics)
                                outcome = parse_search_result(role, result)
                                if excluded_board_pins:
                                    outcome.pins = [pin for pin in outcome.pins if pin.pin_id not in excluded_board_pins]
                                    if not outcome.pins and outcome.code is None:
                                        outcome.code = ReasonCode.PIN_RESULTS_EMPTY
                                    result = {"role": role.value, "code": outcome.code.value if outcome.code else None,
                                              "pin_count": len(outcome.pins)}
                                if self._widget_client is not None:
                                    with self._tracer.phase("widget-enrichment", **trace_fields) as metrics:
                                        outcome = await self._widget_client.enrich_outcome(outcome)
                                        metrics.update(self._tracer.pin_counts(outcome.pins))
                        finally:
                            self._search_slots.release()
                        if outcome.code is not ReasonCode.PIN_SEARCH_UNAVAILABLE or attempts[term_id] >= 3:
                            outcomes[term_id] = outcome
                        else:
                            await self._search_backoff(role, attempts[term_id], "pin_search_unavailable")
                    else:
                        result = await self._mcp_gateway.call_tool(name, arguments)
                except Exception as error:
                    if (isinstance(error, OperationalFailure)
                            and error.failure_code is FailureCode.CONFIGURATION_ERROR):
                        raise
                    result = {"error": str(error)}
                    if search_attempted and role is not None:
                        if attempts[term_id] >= 3:
                            outcomes[term_id] = RoleSearchOutcome(
                                role=role, pins=[], code=ReasonCode.PIN_SEARCH_UNAVAILABLE
                            )
                        else:
                            await self._search_backoff(role, attempts[term_id], "tool_error")
                return {
                    "role": "tool", "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }

            async def flush(tasks):
                try:
                    messages.extend(await asyncio.gather(*tasks))
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    tasks.clear()

            tasks = []
            for call in calls:
                if call["name"] == PINTEREST_SEARCH_TOOL:
                    tasks.append(asyncio.create_task(execute(call)))
                else:
                    await flush(tasks)
                    messages.append(await execute(call))
            await flush(tasks)
        if set(approved) - set(outcomes):
            raise LLMInvalidStructuredOutput(
                "LLM이 모든 승인 역할에 대한 Pinterest 검색 도구를 선택하지 않았다"
            )
        return outcomes

    @staticmethod
    def _approved_query_fragments(resolution, proposed):
        approved = {}
        for term in resolution.terms:
            term_id = term.selection.term_id
            defaults = tuple(term.card["query_fragments"])
            fragments = tuple(proposed.get(term_id, ()))
            approved[term_id] = (
                fragments
                if fragments and all(fragment in defaults for fragment in fragments)
                else defaults
            )
        return approved

    async def _local_search_outcomes(
        self, resolution, exclude_pin_ids, query_fragments_by_term=None
    ):
        # Bound provider exclusions per card, but never reuse any previous board image.
        excluded_board_pins = {pin_id for pins in exclude_pin_ids.values() for pin_id in pins}
        # Search only resolver-approved catalog fragments. No user text or LLM tool selection.
        approved = self._approved_query_fragments(
            resolution, query_fragments_by_term or {}
        )

        async def search(term):
            role = term.selection.role
            term_id = term.selection.term_id
            try:
                async with self._search_slots:
                    search_started = asyncio.get_running_loop().time()
                    async with asyncio.timeout(LOCAL_SEARCH_IO_TIMEOUT_SECONDS):
                        provider = SearXNGPinterestSearchProvider(
                            base_url=self._local_search_url,
                            candidate_limit=24,
                            exclude_pin_ids=tuple(exclude_pin_ids.get(term_id, ())),
                            **({'json_loader': self._search_json_loader} if self._search_json_loader is not None else {}),
                        )
                        outcome = await provider.search(role, approved[term_id])
                        if excluded_board_pins:
                            outcome.pins = [pin for pin in outcome.pins if pin.pin_id not in excluded_board_pins]
                            if not outcome.pins and outcome.code is None:
                                outcome.code = ReasonCode.PIN_RESULTS_EMPTY
                        if self._widget_client is not None:
                            outcome = await self._widget_client.fill_outcome(outcome, timeout_seconds=max(.001,
                                LOCAL_SEARCH_IO_TIMEOUT_SECONDS - .1 - (asyncio.get_running_loop().time() - search_started)))
                        return term_id, outcome
            except Exception:
                return term_id, RoleSearchOutcome(role=role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)

        # gather propagates parent cancellation to each bounded search and widget lookup.
        outcomes = {term.selection.term_id: RoleSearchOutcome(
            role=term.selection.role, code=ReasonCode.PIN_SEARCH_UNAVAILABLE)
            for term in resolution.terms}
        async def collect(term):
            term_id, outcome = await search(term)
            outcomes[term_id] = outcome
        try:
            async with asyncio.timeout(LOCAL_SEARCH_TOTAL_TIMEOUT_SECONDS):
                async with asyncio.TaskGroup() as group:
                    for term in resolution.terms:
                        group.create_task(collect(term))
        except TimeoutError:
            pass
        return outcomes

    async def _search_backoff(self, role: Role, search_attempt: int, reason: str) -> None:
        delay = SEARCH_RETRY_DELAYS_SECONDS[search_attempt - 1]
        with self._tracer.phase("search-retry-wait", role=role.value, search_attempt=search_attempt) as metrics:
            metrics.update(planned_ms=delay * 1000, reason=reason)
            await asyncio.sleep(delay)

    async def _with_heartbeat(self, job: Any, operation: Any) -> None:
        stopped = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(job, stopped))
        execution = asyncio.create_task(operation)
        try:
            done, _ = await asyncio.wait(
                (heartbeat, execution), return_when=asyncio.FIRST_COMPLETED
            )
            if execution in done:
                await execution
            else:
                await heartbeat
                await execution
        finally:
            stopped.set()
            for task in (heartbeat, execution):
                if not task.done():
                    task.cancel()
            await asyncio.gather(heartbeat, execution, return_exceptions=True)

    async def _heartbeat(self, job: Any, stopped: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(stopped.wait(), timeout=self._heartbeat_interval)
                return
            except asyncio.TimeoutError:
                try:
                    await self._jobs.extend_lease(
                        job_id=str(job["job_id"]), attempt=job["attempt"]
                    )
                except DATABASE_ERRORS as error:
                    raise OperationalFailure(classify_failure(error, context="database")) from None

    async def _handle_failure(
        self, job: Any, error: Exception, trace: AttemptTrace
    ) -> None:
        try:
            updated = await self._recovery.handle_attempt_failure(
                job_id=str(job["job_id"]),
                attempt=job["attempt"],
                max_attempts=job["max_attempts"],
                error=error,
            )
        except DATABASE_ERRORS as persistence_error:
            raise OperationalFailure(classify_failure(persistence_error, context="database")) from None
        if updated:
            trace.failed(job, error)
        else:
            trace.stale()

    async def run_forever(self, *, concurrency: int = WORKER_CONCURRENCY) -> None:
        if self._mcp_gateway is not None:
            try:
                await asyncio.wait_for(
                    self._mcp_gateway.list_tools(), timeout=MCP_TOOL_REFRESH_TIMEOUT_SECONDS
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("MCP tool prewarm failed", extra={"error_type": type(error).__name__})

        async def refresh_mcp_tools() -> None:
            while True:
                await asyncio.sleep(MCP_TOOL_REFRESH_INTERVAL_SECONDS)
                try:
                    await asyncio.wait_for(
                        self._mcp_gateway.list_tools(refresh=True),
                        timeout=MCP_TOOL_REFRESH_TIMEOUT_SECONDS,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning("MCP tool refresh failed", extra={"error_type": type(error).__name__})

        async def recover_leases() -> None:
            while True:
                try:
                    await self._recovery.recover_expired_leases()
                    await QuotaRepository(self._pool).recover_stale_reservations(
                        before=datetime.now(timezone.utc) - timedelta(minutes=15)
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.error(
                        "job lease recovery failed",
                        extra={"error_type": type(error).__name__},
                    )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

        async def run_slot() -> None:
            while True:
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.error(
                        "job worker iteration failed",
                        extra={"error_type": type(error).__name__},
                    )
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

        coroutines = [
            recover_leases(),
            *(run_slot() for _ in range(concurrency)),
        ]
        if self._mcp_gateway is not None:
            coroutines.append(refresh_mcp_tools())
        tasks = [asyncio.create_task(coro) for coro in coroutines]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(self._tracer.shutdown)

    async def _update(
        self,
        job_id: str,
        attempt: int,
        status: JobStatus,
        *,
        result: Any | None = None,
    ) -> bool:
        try:
            await self._jobs.update_status(
                job_id=job_id,
                status=status,
                attempt=attempt,
                result=result,
            )
        except StaleJobAttempt:
            return False
        except DATABASE_ERRORS as error:
            raise OperationalFailure(classify_failure(error, context="database")) from None
        return True


async def run_worker(snapshot: CatalogSnapshot, *, http_resources=None) -> None:
    """Keep the polling worker alive without making API startup depend on the DB."""
    from backend.shared.config import get_settings
    from backend.shared.database import close_pool, create_pool
    from backend.services.public_http import PublicHttpResources, current_resources

    if http_resources is None:
        http_resources = current_resources()
    if http_resources is None:
        # Standalone worker owns its transport for the entire polling lifecycle.
        resources = PublicHttpResources()
        try:
            return await run_worker(snapshot, http_resources=resources)
        finally:
            await resources.aclose()

    while True:
        pool = None
        try:
            settings = get_settings()
            if settings.database_url.startswith("sqlite"):
                return
            pool = await create_pool(settings)
            local_llm = settings.llm_backend in ('codex-cli', 'ollama')
            portfolio_budget = None
            if settings.is_portfolio and settings.llm_backend == 'openrouter':
                from backend.services.portfolio_budget import PortfolioLLMCallBudget

                portfolio_budget = PortfolioLLMCallBudget(
                    pool, limit=settings.portfolio_daily_llm_call_limit
                )
            mcp_gateway = (
                None if local_llm or settings.is_portfolio
                else McpToolGateway(mcp_url=settings.mcp_base_url)
            )
            widget_client = http_resources.worker_widget if not local_llm or settings.searxng_base_url else None
            await AgentJobWorker(
                pool, snapshot, mcp_gateway=mcp_gateway, widget_client=widget_client,
                search_json_loader=http_resources.search_json,
                local_search_url=(
                    settings.searxng_base_url
                    if local_llm or settings.is_portfolio else ''
                ),
                personal_terms=PersonalTermRepository(pool),
                grounded_ollama=settings.llm_backend == 'ollama',
                llm_call_reserver=(
                    portfolio_budget.reserve if portfolio_budget is not None else None
                ),
            ).run_forever(
                concurrency=settings.worker_concurrency
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "job worker unavailable; retrying",
                extra={"error_type": type(error).__name__},
            )
        finally:
            if pool is not None:
                await close_pool(pool)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
