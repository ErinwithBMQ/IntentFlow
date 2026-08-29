import asyncio
import json
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel

from app.agent.model_client import ModelClient, OpenAIResponsesModelClient
from app.agent.models import IntentBrief, RunEvent, RunReport, RunResult
from app.agent.runner import DEFAULT_MAX_STEPS, AgentRunner
from app.agent.tools import ToolContext, ToolRegistry
from app.workspaces import DEFAULT_IGNORED_NAMES, WorkspaceService

ReviewStatus = Literal["pending", "accepted", "discarded"]


class RunReviewError(RuntimeError):
    """Raised when a run cannot transition to the requested review state."""


class RunSnapshot(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "stopped"]
    review_status: ReviewStatus
    workspace_relative_path: str
    events: list[RunEvent]
    report: RunReport | None = None


class RunRecord:
    def __init__(
        self,
        run_id: str,
        workspace: Path,
        baseline: Path,
        relative_path: str,
    ) -> None:
        self.id = run_id
        self.workspace = workspace
        self.baseline = baseline
        self.relative_path = relative_path
        self.status: Literal["running", "completed", "failed", "stopped"] = "running"
        self.review_status: ReviewStatus = "pending"
        self.events: list[RunEvent] = []
        self.pending_finished_event: RunEvent | None = None
        self.report: RunReport | None = None
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

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            id=self.id,
            status=self.status,
            review_status=self.review_status,
            workspace_relative_path=self.relative_path,
            events=list(self.events),
            report=self.report,
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
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.repository_root = repository_root.resolve()
        self.records: dict[str, RunRecord] = {}
        self.model_client_factory = model_client_factory
        self.command_factory = command_factory
        self.max_steps = max_steps
        self.workspace_service = workspace_service or WorkspaceService()

    def start(self, intent: IntentBrief) -> RunSnapshot:
        if any(record.status == "running" for record in self.records.values()):
            raise RuntimeError("已有 Agent 任务正在运行，请等待完成或先停止它")

        if self.model_client_factory is None:
            api_key, model, base_url = self._model_config()
        else:
            api_key = model = ""
            base_url = None
        run_id = uuid4().hex[:12]
        relative_path = f"runtime-data/runs/{run_id}/todo-demo"
        workspace = self.repository_root / Path(relative_path)
        run_root = workspace.parent
        baseline = run_root / "baseline" / "todo-demo"
        run_root.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copytree(
                self.repository_root / "examples" / "todo-demo",
                baseline,
                ignore=shutil.ignore_patterns(*DEFAULT_IGNORED_NAMES),
            )
            shutil.copytree(baseline, workspace)
        except Exception:
            shutil.rmtree(run_root, ignore_errors=True)
            raise

        record = RunRecord(run_id, workspace, baseline, relative_path)
        self.records[run_id] = record
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
        context = ToolContext(
            workspace,
            allowed_commands=(
                self.command_factory(workspace)
                if self.command_factory is not None
                else self._node_commands(workspace)
            ),
            stop_event=record.stop_event,
        )
        runner = AgentRunner(
            model_client,
            registry,
            context,
            max_steps=self.max_steps,
            event_sink=record.add_event,
        )
        record.task = asyncio.create_task(self._execute(record, runner, intent))
        return record.snapshot()

    def get(self, run_id: str) -> RunRecord | None:
        return self.records.get(run_id)

    async def stop(self, run_id: str) -> RunSnapshot:
        record = self.records.get(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status == "running":
            record.stop_event.set()
        return record.snapshot()

    def accept(self, run_id: str) -> RunSnapshot:
        record = self._require_record(run_id)
        if record.review_status == "accepted":
            return record.snapshot()
        if record.review_status == "discarded":
            raise RunReviewError("本次运行已放弃，不能再接受")
        if record.status != "completed":
            raise RunReviewError("只有已完成的运行才能接受修改")

        project = self.repository_root / "examples" / "todo-demo"
        self.workspace_service.apply_changes(record.baseline, record.workspace, project)
        record.review_status = "accepted"
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
        return record.snapshot()

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

    def _node_commands(self, workspace: Path) -> dict[str, tuple[str, ...]]:
        node = shutil.which("node")
        demo_root = self.repository_root / "examples" / "todo-demo"
        vitest_cli = demo_root / "node_modules" / "vitest" / "vitest.mjs"
        vite_cli = demo_root / "node_modules" / "vite" / "bin" / "vite.js"
        if node is None or not vitest_cli.is_file() or not vite_cli.is_file():
            raise ValueError("Todo 示例依赖未初始化，请先在 examples/todo-demo 执行 npm install")
        return {
            "test": (node, str(vitest_cli), "run", "--root", str(workspace)),
            "build": (node, str(vite_cli), "build", str(workspace)),
        }


def sse_error(message: str) -> str:
    return f"event: error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n"
