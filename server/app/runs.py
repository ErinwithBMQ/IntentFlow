import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel, Field

from app.agent.context import ContextBudget
from app.agent.model_client import ModelClient, OpenAIResponsesModelClient
from app.agent.models import (
    AgentHistoryItem,
    ContextCheckpoint,
    IntentBrief,
    RunEvent,
    RunMetrics,
    RunReport,
    RunResult,
    ToolApproval,
)
from app.agent.runner import DEFAULT_MAX_STEPS, AgentRunner
from app.agent.tools import ToolContext, ToolRegistry
from app.projects import ProjectRecord
from app.workspaces import DEFAULT_IGNORED_NAMES, WorkspaceService

ReviewStatus = Literal["pending", "accepted", "discarded"]


class RunReviewError(RuntimeError):
    """Raised when a run cannot transition to the requested review state."""


class RunSnapshot(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "stopped"]
    review_status: ReviewStatus
    workspace_relative_path: str
    project_id: str | None = None
    project_name: str | None = None
    project_ignored_names: list[str] = Field(default_factory=lambda: sorted(DEFAULT_IGNORED_NAMES))
    session_id: str | None = None
    trigger_message_id: str | None = None
    intent: IntentBrief | None = None
    approval_mode: Literal["ask", "auto"] = "ask"
    approvals: list[ToolApproval] = Field(default_factory=list)
    events: list[RunEvent]
    report: RunReport | None = None
    context_checkpoint: ContextCheckpoint | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    history: list[AgentHistoryItem] = Field(default_factory=list)


class RunRecord:
    def __init__(
        self,
        run_id: str,
        workspace: Path,
        baseline: Path,
        relative_path: str,
        *,
        project_id: str | None = None,
        project_name: str | None = None,
        project_root: Path | None = None,
        project_ignored_names: frozenset[str] = DEFAULT_IGNORED_NAMES,
        session_id: str | None = None,
        trigger_message_id: str | None = None,
        intent: IntentBrief | None = None,
        snapshot_sink: Callable[[RunSnapshot], None] | None = None,
        approval_timeout_seconds: float = 300.0,
        context_checkpoint: ContextCheckpoint | None = None,
        metrics: RunMetrics | None = None,
        history: list[AgentHistoryItem] | None = None,
    ) -> None:
        self.id = run_id
        self.workspace = workspace
        self.baseline = baseline
        self.relative_path = relative_path
        self.project_id = project_id
        self.project_name = project_name or workspace.name
        self.project_root = project_root.resolve() if project_root is not None else None
        self.project_ignored_names = project_ignored_names
        self.session_id = session_id
        self.trigger_message_id = trigger_message_id
        self.intent = intent
        self.snapshot_sink = snapshot_sink
        self.approval_timeout_seconds = approval_timeout_seconds
        self.approval_mode: Literal["ask", "auto"] = "ask"
        self.approvals: list[ToolApproval] = []
        self._approval_futures: dict[str, asyncio.Future[Literal["approved", "rejected"]]] = {}
        self.status: Literal["running", "completed", "failed", "stopped"] = "running"
        self.review_status: ReviewStatus = "pending"
        self.events: list[RunEvent] = []
        self.pending_finished_event: RunEvent | None = None
        self.report: RunReport | None = None
        self.context_checkpoint = context_checkpoint
        self.metrics = metrics or RunMetrics()
        self.history = history or []
        self.stop_event = asyncio.Event()
        self.changed = asyncio.Condition()
        self.task: asyncio.Task[None] | None = None

    async def add_event(self, event: RunEvent) -> None:
        if event.kind == "run_finished":
            self.pending_finished_event = event
            return
        async with self.changed:
            self.events.append(event)
            self.changed.notify_all()
        self.persist()

    async def finish(self, result: RunResult) -> None:
        async with self.changed:
            self.status = {
                "completed": "completed",
                "partial": "failed",
                "failed": "failed",
                "stopped": "stopped",
            }[result.status]
            self.report = result.report
            if self.pending_finished_event is not None:
                self.events.append(self.pending_finished_event)
                self.pending_finished_event = None
            self.changed.notify_all()
        self.persist()

    def persist(self) -> None:
        if self.snapshot_sink is not None:
            self.snapshot_sink(self.snapshot())

    async def update_context(
        self,
        checkpoint: ContextCheckpoint,
        metrics: RunMetrics,
        history: list[AgentHistoryItem],
    ) -> None:
        async with self.changed:
            self.context_checkpoint = checkpoint
            self.metrics = metrics
            self.history = history
            self.changed.notify_all()
        self.persist()

    def register(self, approval: ToolApproval) -> bool:
        if self.approval_mode == "auto":
            approval.status = "approved"
            approval.decision = "allow_for_run"
            self.approvals.append(approval)
            self.persist()
            return False

        self.approvals.append(approval)
        self._approval_futures[approval.id] = asyncio.get_running_loop().create_future()
        self.persist()
        return True

    async def wait(self, approval_id: str) -> Literal["approved", "rejected", "cancelled"]:
        approval = self._approval(approval_id)
        if approval.status == "approved":
            return "approved"
        if approval.status == "rejected":
            return "rejected"

        future = self._approval_futures[approval_id]
        stop_task = asyncio.create_task(self.stop_event.wait())
        done, _ = await asyncio.wait(
            {future, stop_task},
            timeout=self.approval_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if future in done:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            return future.result()

        approval.status = "cancelled"
        self._approval_futures.pop(approval_id, None)
        if not stop_task.done():
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
        self.persist()
        return "cancelled"

    def resolve_approval(
        self,
        approval_id: str,
        decision: Literal["allow_once", "allow_for_run", "reject"],
    ) -> None:
        if self.status != "running":
            raise RunReviewError("运行已经结束，不能再处理审批")
        approval = self._approval(approval_id)
        if approval.status != "approval_required":
            raise RunReviewError("该审批已经处理，不能重复响应")

        approval.decision = decision
        approval.status = "rejected" if decision == "reject" else "approved"
        if decision == "allow_for_run":
            self.approval_mode = "auto"
        future = self._approval_futures.pop(approval_id, None)
        if future is None or future.done():
            raise RunReviewError("审批请求已经失效")
        future.set_result("rejected" if decision == "reject" else "approved")
        self.persist()

    def _approval(self, approval_id: str) -> ToolApproval:
        approval = next((item for item in self.approvals if item.id == approval_id), None)
        if approval is None:
            raise RunReviewError("审批请求不存在")
        return approval

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            id=self.id,
            status=self.status,
            review_status=self.review_status,
            workspace_relative_path=self.relative_path,
            project_id=self.project_id,
            project_name=self.project_name,
            project_ignored_names=sorted(self.project_ignored_names),
            session_id=self.session_id,
            trigger_message_id=self.trigger_message_id,
            intent=self.intent,
            approval_mode=self.approval_mode,
            approvals=list(self.approvals),
            events=list(self.events),
            report=self.report,
            context_checkpoint=self.context_checkpoint,
            metrics=self.metrics,
            history=self.history,
        )


class RunManager:
    def __init__(
        self,
        repository_root: Path,
        *,
        model_client_factory: Callable[[ToolRegistry], ModelClient] | None = None,
        command_factory: Callable[[Path], dict[str, tuple[str, ...]]] | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        workspace_service: WorkspaceService | None = None,
        snapshot_sink: Callable[[RunSnapshot], None] | None = None,
        approval_timeout_seconds: float = 300.0,
        context_budget: ContextBudget | None = None,
        project_resolver: Callable[[str], ProjectRecord | None] | None = None,
        default_project_root: Path | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.repository_root = repository_root.resolve()
        self.records: dict[str, RunRecord] = {}
        self.model_client_factory = model_client_factory
        self.command_factory = command_factory
        self.max_steps = max_steps
        self.workspace_service = workspace_service
        self.snapshot_sink = snapshot_sink
        self.approval_timeout_seconds = approval_timeout_seconds
        self.context_budget = context_budget
        self.project_resolver = project_resolver
        self.default_project_root = (
            default_project_root.resolve() if default_project_root is not None else None
        )

    def start(
        self,
        intent: IntentBrief,
        *,
        session_id: str | None = None,
        trigger_message_id: str | None = None,
        prior_context: str = "",
        approval_mode: Literal["ask", "auto"] = "ask",
        project: ProjectRecord | None = None,
    ) -> RunSnapshot:
        if any(record.status == "running" for record in self.records.values()):
            raise RuntimeError("已有 Agent 任务正在运行，请等待完成或先停止它")

        if self.model_client_factory is None:
            api_key, model, base_url = self._model_config()
        else:
            api_key = model = ""
            base_url = None
        context_budget = self.context_budget or self._context_budget()
        context_budget.validate_limits()
        project_root, project_id, project_name, ignored_names = self._project_details(project)
        run_id = uuid4().hex[:12]
        relative_path = f"runtime-data/runs/{run_id}/workspace"
        workspace = self.repository_root / Path(relative_path)
        run_root = workspace.parent
        baseline = run_root / "baseline" / "workspace"
        run_root.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copytree(
                project_root,
                baseline,
                ignore=self._copy_ignore(ignored_names),
            )
            shutil.copytree(baseline, workspace)
        except Exception:
            shutil.rmtree(run_root, ignore_errors=True)
            raise

        record = RunRecord(
            run_id,
            workspace,
            baseline,
            relative_path,
            project_id=project_id,
            project_name=project_name,
            project_root=project_root,
            project_ignored_names=ignored_names,
            session_id=session_id,
            trigger_message_id=trigger_message_id,
            intent=intent,
            snapshot_sink=self.snapshot_sink,
            approval_timeout_seconds=self.approval_timeout_seconds,
        )
        record.approval_mode = approval_mode
        self.records[run_id] = record
        record.persist()
        registry = ToolRegistry()
        model_client = (
            self.model_client_factory(registry)
            if self.model_client_factory is not None
            else OpenAIResponsesModelClient(
                registry,
                model,
                api_key=api_key,
                base_url=base_url,
                timeout_seconds=120.0,
            )
        )
        configured_commands = self._project_commands(project, workspace, project_root)
        context = ToolContext(
            workspace,
            allowed_commands=(
                self.command_factory(workspace)
                if self.command_factory is not None
                else configured_commands
            ),
            stop_event=record.stop_event,
            ignored_names=ignored_names,
        )
        runner = AgentRunner(
            model_client,
            registry,
            context,
            max_steps=self.max_steps,
            event_sink=record.add_event,
            approval_controller=record,
            context_budget=context_budget,
            prior_context=prior_context,
            context_sink=record.update_context,
        )
        record.task = asyncio.create_task(self._execute(record, runner, intent))
        return record.snapshot()

    def restore(self, snapshot: RunSnapshot) -> RunSnapshot:
        workspace = self.repository_root / Path(snapshot.workspace_relative_path)
        baseline = workspace.parent / "baseline" / workspace.name
        project = (
            self.project_resolver(snapshot.project_id)
            if snapshot.project_id and self.project_resolver is not None
            else None
        )
        project_root = Path(project.root_path) if project is not None else self.default_project_root
        record = RunRecord(
            snapshot.id,
            workspace,
            baseline,
            snapshot.workspace_relative_path,
            project_id=snapshot.project_id,
            project_name=snapshot.project_name or (project.name if project else workspace.name),
            project_root=project_root,
            project_ignored_names=frozenset(snapshot.project_ignored_names),
            session_id=snapshot.session_id,
            trigger_message_id=snapshot.trigger_message_id,
            intent=snapshot.intent,
            snapshot_sink=self.snapshot_sink,
            approval_timeout_seconds=self.approval_timeout_seconds,
            context_checkpoint=snapshot.context_checkpoint,
            metrics=snapshot.metrics,
            history=snapshot.history,
        )
        record.status = snapshot.status
        record.review_status = snapshot.review_status
        record.events = list(snapshot.events)
        record.report = snapshot.report
        record.approval_mode = snapshot.approval_mode
        record.approvals = list(snapshot.approvals)
        record.context_checkpoint = snapshot.context_checkpoint
        record.metrics = snapshot.metrics
        record.history = list(snapshot.history)
        if record.status == "running":
            record.status = "stopped"
            for approval in record.approvals:
                if approval.status == "approval_required":
                    approval.status = "cancelled"
            record.events.append(
                RunEvent(
                    sequence=len(record.events) + 1,
                    kind="run_finished",
                    phase="finished",
                    status="stopped",
                    action="服务重启，先前运行已停止",
                    reason="运行任务不能跨服务进程继续执行",
                )
            )
        self.records[record.id] = record
        record.persist()
        return record.snapshot()

    def get(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    def has_running(self) -> bool:
        return any(record.status == "running" for record in self.records.values())

    async def stop(self, run_id: str) -> RunSnapshot:
        record = self.records.get(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status == "running":
            record.stop_event.set()
        return record.snapshot()

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        decision: Literal["allow_once", "allow_for_run", "reject"],
    ) -> RunSnapshot:
        record = self._require_record(run_id)
        record.resolve_approval(approval_id, decision)
        return record.snapshot()

    def accept(self, run_id: str) -> RunSnapshot:
        record = self._require_record(run_id)
        if record.review_status == "accepted":
            return record.snapshot()
        if record.review_status == "discarded":
            raise RunReviewError("本次运行已放弃，不能再接受")
        if record.status == "running":
            raise RunReviewError("运行结束后才能接受修改")

        if record.project_root is None:
            raise RunReviewError("运行记录缺少所属项目，无法接受修改")
        project_workspace = self.workspace_service or WorkspaceService(
            ignored_names=record.project_ignored_names
        )
        project_workspace.apply_changes(
            record.baseline,
            record.workspace,
            record.project_root,
        )
        record.review_status = "accepted"
        record.persist()
        return record.snapshot()

    def discard(self, run_id: str) -> RunSnapshot:
        record = self._require_record(run_id)
        if record.review_status == "discarded":
            return record.snapshot()
        if record.review_status == "accepted":
            raise RunReviewError("本次运行已接受，不能再放弃")
        if record.status == "running":
            raise RunReviewError("运行结束后才能放弃修改")

        record.review_status = "discarded"
        record.persist()
        return record.snapshot()

    def delete(self, run_id: str, workspace_relative_path: str | None = None) -> None:
        record = self.records.get(run_id)
        if record is not None and record.status == "running":
            raise RunReviewError("运行中的任务不能随对话删除，请先停止运行")

        relative_path = record.relative_path if record is not None else workspace_relative_path
        if relative_path:
            runs_root = (self.repository_root / "runtime-data" / "runs").resolve()
            run_root = (self.repository_root / Path(relative_path)).resolve().parent
            try:
                relative_run_root = run_root.relative_to(runs_root)
            except ValueError as error:
                raise RunReviewError("运行工作区不在受控目录内，已阻止删除") from error
            if len(relative_run_root.parts) != 1:
                raise RunReviewError("运行工作区路径无效，已阻止删除")
            if run_root.exists():
                shutil.rmtree(run_root)

        self.records.pop(run_id, None)

    async def stream(self, run_id: str) -> AsyncIterator[str]:
        record = self.records.get(run_id)
        if record is None:
            raise KeyError(run_id)

        next_index = 0
        while True:
            async with record.changed:
                await record.changed.wait_for(
                    lambda next_index=next_index: (
                        next_index < len(record.events) or record.status != "running"
                    )
                )
                pending = list(record.events[next_index:])
                next_index = len(record.events)
                finished = record.status != "running"

            for event in pending:
                payload = event.model_dump_json()
                yield f"id: {event.sequence}\nevent: run_event\ndata: {payload}\n\n"
            if finished and next_index == len(record.events):
                break

    def _require_record(self, run_id: str) -> RunRecord:
        record = self.records.get(run_id)
        if record is None:
            raise KeyError(run_id)
        return record

    async def _execute(
        self,
        record: RunRecord,
        runner: AgentRunner,
        intent: IntentBrief,
    ) -> None:
        try:
            result = await runner.run(intent)
        except Exception as error:
            report = RunReport(
                status="failed",
                summary="Agent 运行时发生未处理错误",
                unresolved=[str(error)],
            )
            event = RunEvent(
                sequence=len(record.events) + 1,
                kind="run_finished",
                phase="finished",
                status="failed",
                action=report.summary,
                reason=str(error),
            )
            await record.add_event(event)
            result = RunResult(
                status="failed",
                report=report,
                events=list(record.events),
                steps=0,
            )
        await record.finish(result)

    def _model_config(self) -> tuple[str, str, str | None]:
        config = dotenv_values(self.repository_root / ".env")
        api_key = (config.get("OPENAI_API_KEY") or "").strip()
        model = (config.get("OPENAI_MODEL") or "").strip()
        base_url = (config.get("OPENAI_BASE_URL") or "").strip() or None
        if not api_key or not model:
            raise ValueError("请先在根目录 .env 配置 OPENAI_API_KEY 和 OPENAI_MODEL")
        return api_key, model, base_url

    def _context_budget(self) -> ContextBudget:
        config = dotenv_values(self.repository_root / ".env")
        try:
            return ContextBudget(
                context_window_tokens=int(config.get("AGENT_CONTEXT_WINDOW_TOKENS") or 64_000),
                reserve_output_tokens=int(config.get("AGENT_CONTEXT_RESERVE_TOKENS") or 8_000),
                keep_recent_tokens=int(config.get("AGENT_CONTEXT_KEEP_RECENT_TOKENS") or 12_000),
                compact_at_ratio=float(config.get("AGENT_CONTEXT_COMPACT_AT_RATIO") or 0.8),
                max_tool_output_characters=int(
                    config.get("AGENT_CONTEXT_MAX_TOOL_OUTPUT_CHARACTERS") or 12_000
                ),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"Agent context configuration is invalid: {error}") from error

    def _project_details(
        self,
        project: ProjectRecord | None,
    ) -> tuple[Path, str | None, str, frozenset[str]]:
        if project is not None:
            root = Path(project.root_path).resolve(strict=True)
            return root, project.id, project.name, frozenset(project.ignored_names)
        if self.default_project_root is None:
            raise ValueError("Agent 运行缺少已授权项目")
        root = self.default_project_root.resolve(strict=True)
        return root, None, root.name, DEFAULT_IGNORED_NAMES

    @staticmethod
    def _copy_ignore(ignored_names: frozenset[str]) -> Callable[[str, list[str]], list[str]]:
        ignored_casefold = {name.casefold() for name in ignored_names}

        def ignore(directory: str, names: list[str]) -> list[str]:
            current = Path(directory)
            return [
                name
                for name in names
                if name.casefold() in ignored_casefold or (current / name).is_symlink()
            ]

        return ignore

    @staticmethod
    def _project_commands(
        project: ProjectRecord | None,
        workspace: Path,
        project_root: Path,
    ) -> dict[str, tuple[str, ...]]:
        if project is None:
            return {}
        replacements = {
            "{workspace}": str(workspace),
            "{project}": str(project_root),
        }
        commands: dict[str, tuple[str, ...]] = {}
        for name, configured in (
            ("test", project.test_command),
            ("build", project.build_command),
        ):
            if configured:
                commands[name] = tuple(replacements.get(part, part) for part in configured)
        return commands


def sse_error(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"
