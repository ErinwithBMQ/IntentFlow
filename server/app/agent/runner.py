import asyncio
from collections.abc import Awaitable, Callable

from app.agent.model_client import ModelClient
from app.agent.models import (
    AgentHistoryItem,
    IntentBrief,
    RunEvent,
    RunReport,
    RunResult,
    ToolCall,
    ToolResult,
)
from app.agent.tools import ToolContext, ToolExecution, ToolRegistry

EventSink = Callable[[RunEvent], Awaitable[None]]


async def _ignore_event(event: RunEvent) -> None:
    del event


class AgentRunner:
    def __init__(
        self,
        model_client: ModelClient,
        registry: ToolRegistry,
        context: ToolContext,
        *,
        max_steps: int = 12,
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
        await self._emit(
            kind="run_started",
            phase="planning",
            status="running",
            action=f"开始实现：{intent.title}",
            reason=intent.goal,
        )

        for step in range(1, self.max_steps + 1):
            if self.context.stop_event.is_set():
                return await self._finish_stopped(step - 1)

            try:
                turn = await self.model_client.next_turn(intent, history)
            except Exception as error:
                report = RunReport(
                    status="failed",
                    summary="模型无法给出下一步动作",
                    unresolved=[str(error)],
                )
                return await self._finish(report, step)

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
                    return await self._finish_stopped(step)

                await self._emit_tool_started(call, turn.reason, turn.related_requirement_ids)
                execution = await self.registry.execute(call, self.context)
                if call.name == "apply_patch" and execution.result.ok:
                    verification_evidence.clear()
                if call.name == "run_command":
                    if execution.result.ok:
                        verification_evidence.append(execution.result.summary)
                    else:
                        verification_evidence.clear()
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
                    related_requirement_ids=(
                        call.related_requirement_ids or turn.related_requirement_ids
                    ),
                    tool_name=call.name,
                    target=self._tool_target(call),
                    evidence=[execution.result.summary] if execution.result.ok else [],
                )

                if execution.report is not None:
                    return await self._finish(execution.report, step)

            await asyncio.sleep(0)

        report = RunReport(
            status="failed",
            summary=f"Agent reached the {self.max_steps}-step limit",
            unresolved=["The model did not call report_result before the step limit"],
        )
        return await self._finish(report, self.max_steps)

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

    async def _finish(self, report: RunReport, steps: int) -> RunResult:
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

    async def _finish_stopped(self, steps: int) -> RunResult:
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
        return RunResult(status="stopped", report=report, events=self.events, steps=steps)

    async def _emit(self, **values: object) -> None:
        event = RunEvent(sequence=len(self.events) + 1, **values)
        self.events.append(event)
        await self.event_sink(event)

    @staticmethod
    def _tool_target(call: ToolCall) -> str | None:
        target = call.arguments.get("path") or call.arguments.get("command")
        return str(target) if target is not None else None
