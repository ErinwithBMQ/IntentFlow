import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from app.agent.context import ContextBudget, ContextManager
from app.agent.model_client import ModelClient, ModelClientError
from app.agent.models import (
    AgentHistoryItem,
    ContextCheckpoint,
    IntentBrief,
    ModelTurn,
    RequirementClaim,
    RequirementResult,
    RunEvent,
    RunMetrics,
    RunReport,
    RunResult,
    ToolApproval,
    ToolCall,
    ToolError,
    ToolResult,
)
from app.agent.tools import ToolContext, ToolExecution, ToolRegistry

EventSink = Callable[[RunEvent], Awaitable[None]]
ContextSink = Callable[
    [ContextCheckpoint, RunMetrics, list[AgentHistoryItem]],
    Awaitable[None],
]
DEFAULT_MAX_STEPS = 12
DEFAULT_MODEL_RETRIES = 2
ApprovalOutcome = Literal["approved", "rejected", "cancelled"]


class ApprovalController(Protocol):
    def register(self, approval: ToolApproval) -> bool: ...

    async def wait(self, approval_id: str) -> ApprovalOutcome: ...


class _AutoApprovalController:
    def register(self, approval: ToolApproval) -> bool:
        del approval
        return False

    async def wait(self, approval_id: str) -> ApprovalOutcome:
        del approval_id
        return "approved"


async def _ignore_event(event: RunEvent) -> None:
    del event


async def _ignore_context(
    checkpoint: ContextCheckpoint,
    metrics: RunMetrics,
    history: list[AgentHistoryItem],
) -> None:
    del checkpoint, metrics, history


class _RequirementTracker:
    def __init__(self, intent: IntentBrief) -> None:
        self.requirement_ids = [requirement.id for requirement in intent.requirements]
        self._known_ids = set(self.requirement_ids)
        self.related_files = {requirement_id: [] for requirement_id in self.requirement_ids}
        self.evidence = {requirement_id: [] for requirement_id in self.requirement_ids}
        self.failures = {requirement_id: [] for requirement_id in self.requirement_ids}

    def related_ids(self, call: ToolCall, turn_ids: list[str]) -> list[str]:
        candidates = call.related_requirement_ids or turn_ids
        return list(dict.fromkeys(value for value in candidates if value in self._known_ids))

    def record(
        self,
        call: ToolCall,
        execution: ToolExecution,
        related_ids: list[str],
    ) -> None:
        if call.name == "apply_patch" and execution.result.ok:
            self._clear_evidence()
            path = call.arguments.get("path")
            if path is not None:
                for requirement_id in related_ids:
                    self._append_unique(self.related_files[requirement_id], str(path))

        if call.name == "run_command":
            if execution.result.ok:
                for requirement_id in related_ids:
                    self._append_unique(
                        self.evidence[requirement_id],
                        execution.result.summary,
                    )
            else:
                self._clear_evidence()

        if not execution.result.ok:
            for requirement_id in related_ids:
                self._append_unique(
                    self.failures[requirement_id],
                    execution.result.summary,
                )

    def claims_error(self, claims: list[RequirementClaim]) -> str | None:
        claim_ids = [claim.requirement_id for claim in claims]
        duplicates = sorted(
            requirement_id
            for requirement_id in set(claim_ids)
            if claim_ids.count(requirement_id) > 1
        )
        unknown = sorted(set(claim_ids) - self._known_ids)
        missing = sorted(self._known_ids - set(claim_ids))
        if not duplicates and not unknown and not missing:
            return None

        problems: list[str] = []
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown: {', '.join(unknown)}")
        if duplicates:
            problems.append(f"duplicated: {', '.join(duplicates)}")
        return (
            "Requirement claims must cover each IntentBrief requirement exactly once ("
            + "; ".join(problems)
            + ")"
        )

    def results(self, claims: list[RequirementClaim] | None = None) -> list[RequirementResult]:
        claim_by_id = {claim.requirement_id: claim for claim in claims or []}
        return [
            self._result(requirement_id, claim_by_id.get(requirement_id))
            for requirement_id in self.requirement_ids
        ]

    def _result(
        self,
        requirement_id: str,
        claim: RequirementClaim | None,
    ) -> RequirementResult:
        related_files = self.related_files[requirement_id]
        evidence = self.evidence[requirement_id]
        failures = self.failures[requirement_id]

        if claim is not None and claim.status in {"failed", "unresolved"}:
            status = claim.status
        elif evidence:
            status = "verified"
        elif related_files:
            status = "implemented"
        elif failures:
            status = "failed"
        else:
            status = "unresolved"

        default_summary = {
            "verified": "已通过关联的测试或构建验证",
            "implemented": "已修改关联文件，但缺少需求级验证证据",
            "failed": failures[-1] if failures else "实现或验证失败",
            "unresolved": "未获得实现或验证记录",
        }[status]
        summary = default_summary
        if claim is not None and not (claim.status == "verified" and status != "verified"):
            summary = claim.summary
        return RequirementResult(
            requirement_id=requirement_id,
            status=status,
            summary=summary,
            related_files=list(related_files),
            evidence=list(evidence),
        )

    def _clear_evidence(self) -> None:
        for items in self.evidence.values():
            items.clear()

    @staticmethod
    def _append_unique(items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)


class AgentRunner:
    def __init__(
        self,
        model_client: ModelClient,
        registry: ToolRegistry,
        context: ToolContext,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
        event_sink: EventSink = _ignore_event,
        approval_controller: ApprovalController | None = None,
        context_manager: ContextManager | None = None,
        context_budget: ContextBudget | None = None,
        prior_context: str = "",
        context_sink: ContextSink = _ignore_context,
        max_model_retries: int = DEFAULT_MODEL_RETRIES,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model_client = model_client
        self.registry = registry
        self.context = context
        self.max_steps = max_steps
        self.event_sink = event_sink
        self.approval_controller = approval_controller or _AutoApprovalController()
        self.context_manager = context_manager
        self.context_budget = context_budget
        self.prior_context = prior_context
        self.context_sink = context_sink
        self.max_model_retries = max_model_retries
        self.events: list[RunEvent] = []
        self._history: list[AgentHistoryItem] = []

    async def run(self, intent: IntentBrief) -> RunResult:
        self.events = []
        history: list[AgentHistoryItem] = []
        self._history = history
        verification_evidence: list[str] = []
        tracker = _RequirementTracker(intent)
        if self.context_manager is None:
            summarizer = (
                self.model_client
                if hasattr(self.model_client, "summarize_context")
                else None
            )
            self.context_manager = ContextManager(
                intent,
                budget=self.context_budget,
                summarizer=summarizer,
                prior_context=self.prior_context,
            )
        await self._emit(
            kind="run_started",
            phase="planning",
            status="running",
            action=f"开始实现：{intent.title}",
            reason=intent.goal,
        )

        for step in range(1, self.max_steps + 1):
            if self.context.stop_event.is_set():
                return await self._finish_stopped(step - 1, tracker)

            try:
                prepared = await self.context_manager.prepare(intent, history, step=step)
                started_at = monotonic()
                turn = await self._next_turn_with_retry(intent, prepared.history)
                if turn is None:
                    return await self._finish_stopped(step - 1, tracker)
                self.context_manager.record_turn(
                    turn,
                    prepared,
                    step=step,
                    duration_ms=max(0, int((monotonic() - started_at) * 1000)),
                )
                history.append(turn)
                await self._sync_context()
            except Exception as error:
                kind = error.kind if isinstance(error, ModelClientError) else "unexpected"
                report = RunReport(
                    status="failed",
                    summary="模型无法给出下一步动作",
                    unresolved=[f"{kind}: {error}"],
                )
                return await self._finish(report, step, tracker)

            await self._emit(
                kind="model_turn",
                phase="planning",
                status="running",
                action=turn.action,
                reason=turn.reason,
                related_requirement_ids=turn.related_requirement_ids,
            )

            for call in turn.tool_calls:
                if self.context.stop_event.is_set():
                    return await self._finish_stopped(step, tracker)

                related_ids = tracker.related_ids(call, turn.related_requirement_ids)
                preview = self.registry.approval_preview(call, self.context)
                prepared_execution = preview if isinstance(preview, ToolExecution) else None
                if preview is not None and prepared_execution is None:
                    approval = ToolApproval(
                        id=f"approval-{uuid4().hex[:12]}",
                        tool_call_id=call.id,
                        tool_name=call.name,
                        target=preview.target,
                        reason=call.reason or turn.reason,
                        patch=preview.patch,
                        status="approval_required",
                    )
                    requires_user = self.approval_controller.register(approval)
                    if requires_user:
                        await self._emit(
                            kind="approval_required",
                            phase="acting",
                            status="running",
                            action=f"等待批准修改 {preview.target}",
                            reason=approval.reason,
                            related_requirement_ids=related_ids,
                            tool_name=call.name,
                            target=preview.target,
                            approval_id=approval.id,
                            patch=preview.patch,
                            approval_status="approval_required",
                        )
                    outcome = await self.approval_controller.wait(approval.id)
                    self.context_manager.record_approval(preview.target, outcome)
                    await self._sync_context()
                    if outcome == "cancelled":
                        return await self._finish_stopped(step, tracker)
                    if requires_user:
                        await self._emit(
                            kind="approval_resolved",
                            phase="acting",
                            status="succeeded" if outcome == "approved" else "failed",
                            action=(
                                f"已批准修改 {preview.target}"
                                if outcome == "approved"
                                else f"已拒绝修改 {preview.target}"
                            ),
                            reason="用户已处理本次修改申请",
                            related_requirement_ids=related_ids,
                            tool_name=call.name,
                            target=preview.target,
                            approval_id=approval.id,
                            patch=preview.patch,
                            approval_status=outcome,
                        )
                    if outcome == "rejected":
                        rejected_result = ToolResult(
                                call_id=call.id,
                                tool_name=call.name,
                                ok=False,
                                summary="User rejected this file modification",
                                output=(
                                    "The proposed patch was not applied. Adjust the plan or "
                                    "finish with the requirement unresolved."
                                ),
                                error=ToolError(
                                    kind="user_rejected",
                                    message="User rejected this file modification",
                                    retryable=False,
                                    suggestion=(
                                        "Choose a different approach or leave the "
                                        "requirement unresolved."
                                    ),
                                ),
                            )
                        history.append(rejected_result)
                        self.context_manager.record_tool(call, rejected_result)
                        await self._sync_context()
                        continue

                await self._emit_tool_started(call, turn.reason, related_ids)
                execution = prepared_execution or await self.registry.execute(call, self.context)
                if call.name == "apply_patch" and execution.result.ok:
                    verification_evidence.clear()
                if call.name == "run_command":
                    if execution.result.ok:
                        verification_evidence.append(execution.result.summary)
                    else:
                        verification_evidence.clear()
                tracker.record(call, execution, related_ids)
                execution = self._attach_requirement_results(call, execution, tracker)
                execution = self._require_real_completion_evidence(
                    call,
                    execution,
                    verification_evidence,
                )
                history.append(execution.result)
                self.context_manager.record_tool(call, execution.result)
                await self._sync_context()
                await self._emit(
                    kind="tool_finished",
                    phase="verifying" if call.name == "run_command" else "acting",
                    status="succeeded" if execution.result.ok else "failed",
                    action=execution.result.summary,
                    reason=call.reason or turn.reason,
                    related_requirement_ids=related_ids,
                    tool_name=call.name,
                    target=self._tool_target(call),
                    evidence=[execution.result.summary] if execution.result.ok else [],
                )

                if execution.report is not None:
                    return await self._finish(execution.report, step, tracker)

            await asyncio.sleep(0)

        report = RunReport(
            status="failed",
            summary=f"Agent reached the {self.max_steps}-step limit",
            unresolved=["The model did not call report_result before the step limit"],
        )
        return await self._finish(report, self.max_steps, tracker)

    async def _next_turn_with_retry(
        self,
        intent: IntentBrief,
        history: list[AgentHistoryItem],
    ) -> ModelTurn | None:
        for attempt in range(self.max_model_retries + 1):
            try:
                return await self._next_turn_or_stop(intent, history)
            except ModelClientError as error:
                if not error.retryable or attempt >= self.max_model_retries:
                    raise
                await asyncio.sleep(0)
        raise RuntimeError("unreachable model retry state")

    async def _next_turn_or_stop(
        self,
        intent: IntentBrief,
        history: list[AgentHistoryItem],
    ) -> ModelTurn | None:
        model_task = asyncio.create_task(self.model_client.next_turn(intent, history))
        stop_task = asyncio.create_task(self.context.stop_event.wait())
        done, _ = await asyncio.wait(
            {model_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done and self.context.stop_event.is_set():
            model_task.cancel()
            await asyncio.gather(model_task, return_exceptions=True)
            return None

        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        return model_task.result()

    @staticmethod
    def _attach_requirement_results(
        call: ToolCall,
        execution: ToolExecution,
        tracker: _RequirementTracker,
    ) -> ToolExecution:
        if execution.report is None:
            return execution

        claims_error = tracker.claims_error(execution.requirement_claims)
        if claims_error is not None:
            return ToolExecution(
                result=ToolResult(
                    call_id=call.id,
                    tool_name=call.name,
                    ok=False,
                    summary="Requirement claims failed validation",
                    output=claims_error,
                )
            )

        report = execution.report.model_copy(
            update={"requirement_results": tracker.results(execution.requirement_claims)}
        )
        return execution.model_copy(update={"report": report})

    @staticmethod
    def _require_real_completion_evidence(
        call: ToolCall,
        execution: ToolExecution,
        verification_evidence: list[str],
    ) -> ToolExecution:
        report = execution.report
        if report is None or report.status != "completed":
            return execution
        if verification_evidence:
            return execution.model_copy(
                update={"report": report.model_copy(update={"evidence": verification_evidence})}
            )

        return ToolExecution(
            result=ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=False,
                summary="Cannot complete before a test or build command succeeds",
                output="Call run_command successfully, then report the result again.",
            )
        )

    async def _emit_tool_started(
        self,
        call: ToolCall,
        reason: str,
        related_requirement_ids: list[str],
    ) -> None:
        await self._emit(
            kind="tool_started",
            phase="verifying" if call.name == "run_command" else "acting",
            status="running",
            action=call.action or f"调用 {call.name}",
            reason=call.reason or reason,
            related_requirement_ids=call.related_requirement_ids or related_requirement_ids,
            tool_name=call.name,
            target=self._tool_target(call),
        )

    async def _finish(
        self,
        report: RunReport,
        steps: int,
        tracker: _RequirementTracker,
    ) -> RunResult:
        if not report.requirement_results:
            report = report.model_copy(update={"requirement_results": tracker.results()})
        status = "succeeded" if report.status == "completed" else "failed"
        await self._emit(
            kind="run_finished",
            phase="finished",
            status=status,
            action=report.summary,
            reason="Agent 已提交带证据的最终报告",
            evidence=report.evidence,
        )
        if self.context_manager is not None:
            self.context_manager.checkpoint.unresolved = list(report.unresolved)
            self.context_manager.finish()
            await self._sync_context()
        return RunResult(status=report.status, report=report, events=self.events, steps=steps)

    async def _finish_stopped(
        self,
        steps: int,
        tracker: _RequirementTracker,
    ) -> RunResult:
        report = RunReport(
            status="partial",
            summary="Agent run stopped by user",
            unresolved=["Run stopped before a final report was produced"],
        )
        await self._emit(
            kind="run_finished",
            phase="finished",
            status="stopped",
            action=report.summary,
            reason="收到停止信号",
        )
        if self.context_manager is not None:
            self.context_manager.checkpoint.unresolved = list(report.unresolved)
            self.context_manager.finish()
            await self._sync_context()
        return RunResult(
            status="stopped",
            report=report.model_copy(update={"requirement_results": tracker.results()}),
            events=self.events,
            steps=steps,
        )

    async def _emit(self, **values: object) -> None:
        event = RunEvent(sequence=len(self.events) + 1, **values)
        self.events.append(event)
        await self.event_sink(event)

    async def _sync_context(self) -> None:
        if self.context_manager is None:
            return
        await self.context_sink(
            self.context_manager.checkpoint.model_copy(deep=True),
            self.context_manager.metrics.model_copy(deep=True),
            [item.model_copy(deep=True) for item in self._history],
        )

    @staticmethod
    def _tool_target(call: ToolCall) -> str | None:
        target = call.arguments.get("path") or call.arguments.get("command")
        return str(target) if target is not None else None
