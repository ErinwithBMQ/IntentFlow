import asyncio
from collections.abc import Awaitable, Callable

from app.agent.model_client import ModelClient
from app.agent.models import (
    AgentHistoryItem,
    IntentBrief,
    ModelTurn,
    RequirementClaim,
    RequirementResult,
    RunEvent,
    RunReport,
    RunResult,
    ToolCall,
    ToolResult,
)
from app.agent.tools import ToolContext, ToolExecution, ToolRegistry

EventSink = Callable[[RunEvent], Awaitable[None]]
DEFAULT_MAX_STEPS = 12


async def _ignore_event(event: RunEvent) -> None:
    del event


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
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.model_client = model_client
        self.registry = registry
        self.context = context
        self.max_steps = max_steps
        self.event_sink = event_sink
        self.events: list[RunEvent] = []

    async def run(self, intent: IntentBrief) -> RunResult:
        self.events = []
        history: list[AgentHistoryItem] = []
        verification_evidence: list[str] = []
        tracker = _RequirementTracker(intent)
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
                turn = await self._next_turn_or_stop(intent, history)
                if turn is None:
                    return await self._finish_stopped(step - 1, tracker)
            except Exception as error:
                report = RunReport(
                    status="failed",
                    summary="模型无法给出下一步动作",
                    unresolved=[str(error)],
                )
                return await self._finish(report, step, tracker)

            history.append(turn)
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
                await self._emit_tool_started(call, turn.reason, related_ids)
                execution = await self.registry.execute(call, self.context)
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

    @staticmethod
    def _tool_target(call: ToolCall) -> str | None:
        target = call.arguments.get("path") or call.arguments.get("command")
        return str(target) if target is not None else None
