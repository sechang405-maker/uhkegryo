"""Execute claimed jobs through the LLM, resolver, and response assembler."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Mapping

from backend.schemas.enums import AgentStatus, FailureCode, JobStatus, ReasonCode, Role
from backend.schemas.models import AgentResult
from backend.services.catalog_repository import CatalogSnapshot
from backend.services.conversation_memory import ConversationMemory
from backend.services import conversation_context
from backend.services import reference_update
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
from backend.services.mcp_pinterest_search import parse_search_result, pop_search_diagnostics
from backend.services.mcp_tool_gateway import McpToolGateway
from backend.services.pinterest_widget import PinterestWidgetClient
from backend.services.resolver import ResolutionResult
from backend.services.response_assembler import RoleSearchOutcome, assemble
from backend.services.failure_mapping import DATABASE_ERRORS, OperationalFailure, classify_failure

logger = logging.getLogger(__name__)
WORKER_CONCURRENCY = 5
POLL_INTERVAL_SECONDS = 1
SEARCH_RETRY_DELAYS_SECONDS = (1, 2)
SEARCH_CONCURRENCY = 3
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
        heartbeat_interval: float = 10,
        tracer: JobTracer | None = None,
    ) -> None:
        self._pool = pool
        self._jobs = JobRepository(pool)
        self._memory = ConversationMemory(pool)
        self._recovery = JobRetryRecovery(pool)
        self._snapshot = snapshot
        self._adapter = adapter
        self._mcp_gateway = mcp_gateway
        self._widget_client = widget_client
        self._search_slots = asyncio.Semaphore(SEARCH_CONCURRENCY)
        self._heartbeat_interval = heartbeat_interval
        self._tracer = tracer if tracer is not None else JobTracer.from_settings()

    async def run_once(
        self,
        *,
        search_outcomes: Mapping[Role, RoleSearchOutcome] | None = None,
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
                    user_message="이 서비스는 텍스트로 설명한 캐릭터 레퍼런스 탐색을 지원합니다.",
                )
                if await self._update(job_id, attempt, JobStatus.COMPLETED, result=result):
                    trace.completed(result)
                else:
                    trace.stale()
                return
            if self._adapter is None:
                self._adapter = LLMInterpretationAdapter()
            with trace.stage("memory-context"):
                context = await conversation_context.prepare(self._memory, job, self._adapter, trace)
            recalled, recall_only = await conversation_context.recall(
                self._memory, job, context, self._adapter, trace)
            state = context["state"]
            if recall_only:
                result = recalled
            else:
                previous = reference_update.previous_terms(context, self._snapshot)
                refresh = context.get("reference_action") in ("refresh_all", "refresh_roles")
                interpretation = None
                with trace.stage("validating"):
                    feedback = job.get("validation_feedback_json")
                    if isinstance(feedback, str):
                        feedback = json.loads(feedback)
                    if refresh:
                        resolution = reference_update.refresh_resolution(previous, self._snapshot, context)
                    else:
                        interpretation = await self._adapter.interpret(
                            job["request_text"], **conversation_context.trace_args(job),
                            active_cards_json=format_active_cards_json(self._snapshot),
                            session_context=conversation_context.prompt_context(context),
                            **({"validation_feedback": feedback} if feedback else {}),
                        )
                        resolution = await conversation_context.validate(
                            self._memory, job, interpretation, self._snapshot)
                        resolution = reference_update.select_searches(resolution, previous)
                with trace.stage("searching"):
                    with self._tracer.phase("search-status-update"):
                        if not await self._update(job_id, attempt, JobStatus.SEARCHING):
                            trace.stale()
                            return
                    if search_outcomes is None:
                        search_outcomes = await self._search_outcomes(
                            resolution, request_text=str(job["request_text"]),
                            **({"exclude_pin_ids": {role: list(dict.fromkeys(pin.pin_id
                                for term in previous.values() for pin in term.pins))
                                for role in previous}} if refresh else {}),
                        )
                with self._tracer.phase("search-result-assembly") as metrics:
                    result = assemble(resolution, self._snapshot, search_outcomes,
                        answer_text=("기존 조건은 유지하고 요청한 역할의 레퍼런스를 다시 찾았어요."
                            if context.get("reference_action") == "refresh_roles"
                            else "기존 조건은 유지하고 전체 레퍼런스를 다시 찾았어요.") if refresh else interpretation.answer_text)
                    if refresh and result.reference_plan is not None and result.reason_codes:
                        result.answer_text = "기존 조건은 유지했지만 일부 새 레퍼런스를 찾지 못했어요. 검색 결과 안내를 확인해 주세요."
                    result = reference_update.merge_preserved(result, previous, interpretation)
                    result = reference_update.annotate(result, context, [term.selection.role for term in resolution.terms])
                    metrics.update(
                        role_count=len(search_outcomes),
                        pin_count=sum(len(outcome.pins) for outcome in search_outcomes.values()),
                    )
                if recalled is not None:
                    result.memory_answer, result.sources = recalled.memory_answer, recalled.sources
            with trace.stage("rendering"):
                if not await self._update(job_id, attempt, JobStatus.RENDERING):
                    trace.stale()
                    return
                with self._tracer.phase("conversation-state-update") as metrics:
                    if not recall_only and not refresh:
                        state = conversation_context.next_state(context, job, interpretation, result)
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
        self, resolution: ResolutionResult, *, request_text: str, exclude_pin_ids=None
    ) -> Mapping[Role, RoleSearchOutcome]:
        if self._mcp_gateway is None or not resolution.terms:
            return {}
        adapter = self._adapter
        if not hasattr(adapter, "request_mcp_tool_calls"):
            raise ValueError("해석 어댑터가 MCP tool calling을 지원하지 않습니다")
        with self._tracer.phase("mcp-tools-list"):
            tools = await self._mcp_gateway.list_tools()
        approved = {
            term.selection.role: tuple(term.card["query_fragments"])
            for term in resolution.terms
        }
        outcomes: dict[Role, RoleSearchOutcome] = {}
        attempts: dict[Role, int] = {role: 0 for role in approved}
        tool_call_count = 0
        messages = [
            {"role": "system", "content": (
                "Use the registered MCP tools to fulfill the request. For Pinterest searches, "
                "call search_pinterest_pins only with an approved role and that role's exact "
                "query_fragments. Never invent or alter fragments. Use other listed tools "
                "when needed. Select independent searches for all unfinished approved roles "
                "together in one response, at most once per role. After tool results, retry "
                "only unfinished roles; do not search completed roles again. "
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
                call_round=call_round, purpose=purpose, pending_roles=[role.value for role in pending],
            ) as metrics:
                calls = await adapter.request_mcp_tool_calls(messages, tools, required=bool(pending))
                metrics.update(call_count=len(calls), selected_roles=sorted({
                    call["arguments"].get("role") for call in calls
                    if call["name"] == PINTEREST_SEARCH_TOOL
                    and isinstance(call["arguments"].get("role"), str)
                    and call["arguments"].get("role") in {role.value for role in approved}
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
            batch_roles: set[Role] = set()

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
                try:
                    if name == PINTEREST_SEARCH_TOOL:
                        role = Role(arguments.get("role"))
                        fragments = arguments.get("query_fragments")
                        if role not in approved or role in outcomes:
                            raise ValueError("Pinterest search arguments are outside approved terms")
                        if fragments != list(approved[role]):
                            raise ValueError("Pinterest search arguments are outside approved terms")
                        if role in batch_roles:
                            raise ValueError("Duplicate Pinterest role in one response")
                        if attempts[role] >= 3:
                            raise ValueError("Pinterest search retry limit exceeded")
                        batch_roles.add(role)
                        attempts[role] += 1
                        search_attempted = True
                    if search_attempted:
                        trace_fields = {"role": role.value, "search_attempt": attempts[role]}
                        with self._tracer.phase("search-slot-wait", **trace_fields):
                            await self._search_slots.acquire()
                        try:
                            with self._tracer.search(role.value, list(approved[role]),
                                                     search_attempt=attempts[role]) as search_span:
                                with self._tracer.phase("mcp-search-call", **trace_fields):
                                    actual_arguments = {"role": role.value, "query_fragments": list(approved[role])}
                                    excluded = (exclude_pin_ids or {}).get(role, [])
                                    if excluded:
                                        actual_arguments["exclude_pin_ids"] = excluded
                                    result = await self._mcp_gateway.call_tool(name, actual_arguments)
                                diagnostics = pop_search_diagnostics(result)
                                self._tracer.search_result(search_span, diagnostics)
                                outcome = parse_search_result(role, result)
                                if excluded:
                                    outcome.pins = [pin for pin in outcome.pins if pin.pin_id not in excluded]
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
                        if outcome.code is not ReasonCode.PIN_SEARCH_UNAVAILABLE or attempts[role] >= 3:
                            outcomes[role] = outcome
                        else:
                            await self._search_backoff(role, attempts[role], "pin_search_unavailable")
                    else:
                        result = await self._mcp_gateway.call_tool(name, arguments)
                except Exception as error:
                    if (isinstance(error, OperationalFailure)
                            and error.failure_code is FailureCode.CONFIGURATION_ERROR):
                        raise
                    result = {"error": str(error)}
                    if search_attempted and role is not None:
                        if attempts[role] >= 3:
                            outcomes[role] = RoleSearchOutcome(
                                role=role, pins=[], code=ReasonCode.PIN_SEARCH_UNAVAILABLE
                            )
                        else:
                            await self._search_backoff(role, attempts[role], "tool_error")
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


async def run_worker(snapshot: CatalogSnapshot) -> None:
    """Keep the polling worker alive without making API startup depend on the DB."""
    from backend.shared.config import get_settings
    from backend.shared.database import close_pool, create_pool

    while True:
        pool = None
        try:
            settings = get_settings()
            if settings.database_url.startswith("sqlite"):
                return
            pool = await create_pool(settings)
            mcp_gateway = McpToolGateway(mcp_url=settings.mcp_base_url)
            widget_client = PinterestWidgetClient()
            await AgentJobWorker(
                pool, snapshot, mcp_gateway=mcp_gateway, widget_client=widget_client
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
