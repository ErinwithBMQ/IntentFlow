import asyncio
import sqlite3
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.agent.model_client import FakeModelClient
from app.agent.models import (
    ContextCheckpoint,
    ContextRoundMetrics,
    IntentBrief,
    IntentRequirement,
    ModelTurn,
    RunEvent,
    RunMetrics,
    RunReport,
    ToolApproval,
    ToolCall,
    ToolResult,
)
from app.checkpoints import RunCheckpoint
from app.conversation_service import build_project_context
from app.intent.compiler import IntentRequestDecision
from app.intent.models import CanvasConnection, CanvasNote, CanvasPosition, IntentCanvas
from app.projects import ProjectRegistry
from app.runs import RunManager, RunSnapshot
from app.session_context import SessionContextBuilder
from app.sessions import ProjectRecord, SessionStore


def make_store(path: Path) -> SessionStore:
    store = SessionStore(path)
    store.ensure_project(
        ProjectRecord(
            id="todo-demo",
            name="todo-demo",
            relative_path="examples/todo-demo",
        )
    )
    return store


def sample_brief() -> IntentBrief:
    return IntentBrief(
        title="增加筛选",
        goal="允许筛选未完成任务",
        requirements=[
            IntentRequirement(
                id="REQ-01",
                description="显示未完成任务",
                acceptance_criteria=["筛选结果正确"],
                source_ids=["message-1"],
            )
        ],
    )


def sample_plan_canvas() -> IntentCanvas:
    return IntentCanvas(
        notes=[
            CanvasNote(
                id="goal",
                text="规划待办筛选",
                label="idea",
                position=CanvasPosition(x=40, y=120),
            ),
            CanvasNote(
                id="filter",
                text="显示未完成任务",
                label="behavior",
                position=CanvasPosition(x=340, y=80),
            ),
            CanvasNote(
                id="check",
                text="筛选结果正确",
                label="acceptance",
                position=CanvasPosition(x=640, y=80),
            ),
        ],
        connections=[
            CanvasConnection(id="e1", source="goal", target="filter", label="包含"),
            CanvasConnection(id="e2", source="filter", target="check", label="验收"),
        ],
    )


def test_session_store_migrates_and_persists_approval_mode(tmp_path) -> None:
    database = tmp_path / "intentflow.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              title TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
            ("legacy-session", "todo-demo", "旧对话", "created", "updated"),
        )

    store = SessionStore(database)
    restored = store.get_session("legacy-session")
    updated = store.set_approval_mode("legacy-session", "auto")

    assert restored is not None
    assert restored.approval_mode == "ask"
    assert updated.approval_mode == "auto"
    assert SessionStore(database).get_session("legacy-session").approval_mode == "auto"


def test_session_store_restores_messages_canvas_and_runs(tmp_path) -> None:
    database = tmp_path / "intentflow.db"
    store = make_store(database)
    session = store.create_session("todo-demo")
    canvas = IntentCanvas(
        notes=[
            CanvasNote(
                id="note-1",
                text="保留筛选按钮",
                position=CanvasPosition(x=12, y=24),
            )
        ]
    )
    canvas_snapshot = store.add_canvas_snapshot(session.id, canvas)
    message = store.add_message(
        session.id,
        "user",
        "agent",
        "增加未完成筛选",
        canvas_snapshot_id=canvas_snapshot.id,
    )
    task_draft = store.add_task_draft(
        session.id,
        message.id,
        sample_brief(),
        status="confirmed",
        canvas=canvas,
    )
    run = RunSnapshot(
        id="run-1",
        status="completed",
        review_status="pending",
        workspace_relative_path="runtime-data/runs/run-1/todo-demo",
        session_id=session.id,
        trigger_message_id=message.id,
        task_draft_id=task_draft.id,
        intent=sample_brief(),
        events=[
            RunEvent(
                sequence=1,
                kind="tool_finished",
                phase="verifying",
                status="failed",
                action="Command is not configured: test",
                reason="项目没有配置测试命令",
                tool_name="run_command",
                target="test",
                verification_status="not_configured",
            )
        ],
        context_checkpoint=ContextCheckpoint(
            summary="已完成筛选实现",
            modified_files=["src/filter.ts"],
            verification_results=["test exited with code 0"],
        ),
        metrics=RunMetrics(
            model_turns=1,
            tool_calls=1,
            rounds=[ContextRoundMetrics(step=1, estimated_input_tokens=120)],
        ),
        history=[
            ModelTurn(action="检查筛选", reason="确认当前实现"),
            ToolResult(
                call_id="read-1",
                tool_name="read_file",
                ok=True,
                summary="Read src/filter.ts",
                output="export const filter = true;",
            ),
        ],
    )
    store.save_run(run)
    store.attach_run(message.id, run.id)

    canvas.notes[0].text = "外部修改不会改变快照"
    restored = make_store(database).get_detail(session.id)

    assert restored is not None
    assert restored.session.title == "增加未完成筛选"
    assert restored.session.approval_mode == "ask"
    assert restored.messages[0].id == message.id
    assert restored.messages[0].run_id == run.id
    assert restored.canvas_snapshots[0].canvas.notes[0].text == "保留筛选按钮"
    assert restored.task_drafts[0].version == 1
    assert restored.task_drafts[0].status == "confirmed"
    assert restored.task_drafts[0].source_message_id == message.id
    assert restored.task_drafts[0].canvas is not None
    assert restored.task_drafts[0].canvas.notes[0].text == "保留筛选按钮"
    assert restored.task_drafts[0].intent == sample_brief()
    assert restored.runs[0].task_draft_id == task_draft.id
    assert restored.runs[0].intent == sample_brief()
    assert restored.runs[0].context_checkpoint.summary == "已完成筛选实现"
    assert restored.runs[0].metrics.rounds[0].estimated_input_tokens == 120
    assert restored.runs[0].events[0].verification_status == "not_configured"
    assert restored.runs[0].history[1].output == "export const filter = true;"


def test_run_context_only_includes_reviewed_outcomes(tmp_path) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    store.add_message(session.id, "user", "agent", "先实现筛选")
    store.add_message(session.id, "assistant", "agent", "第一轮已经完成")

    for run_id, review_status, summary, file_name in [
        ("run-applied", "accepted", "筛选已完成", "src/filter.ts"),
        ("run-discarded", "discarded", "排序方案未采用", "src/sort.ts"),
        ("run-pending", "pending", "仍待审查", "src/pending.ts"),
    ]:
        store.save_run(
            RunSnapshot(
                id=run_id,
                status="completed",
                review_status=review_status,
                workspace_relative_path=f"runtime-data/runs/{run_id}/todo-demo",
                session_id=session.id,
                intent=sample_brief(),
                events=[],
                report=RunReport(status="completed", summary=summary),
                context_checkpoint=ContextCheckpoint(
                    modified_files=[file_name],
                    verification_results=["test exited with code 0"],
                ),
            )
        )

    context = store.build_run_context(session.id)

    assert "先实现筛选" in context
    assert "run-applied: kept in project" in context
    assert "src/filter.ts" in context
    assert "run-discarded: undone from project" in context
    assert "src/sort.ts" in context
    assert "run-pending" not in context
    assert "src/pending.ts" not in context


def test_session_context_exposes_authoritative_review_and_approval_facts(tmp_path) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    current = store.add_message(session.id, "user", "agent", "我刚才选择了什么？")
    store.save_run(
        RunSnapshot(
            id="run-discarded",
            status="completed",
            review_status="discarded",
            workspace_relative_path="runtime-data/runs/run-discarded/todo-demo",
            session_id=session.id,
            intent=sample_brief(),
            approvals=[
                ToolApproval(
                    id="approval-1",
                    tool_call_id="patch-1",
                    tool_name="apply_patch",
                    status="rejected",
                    decision="reject",
                    reason="用户拒绝本次修改",
                    patch="--- a/src/filter.ts\n+++ b/src/filter.ts\n",
                )
            ],
            events=[],
            report=RunReport(status="completed", summary="修改未采用"),
            context_checkpoint=ContextCheckpoint(modified_files=["src/filter.ts"]),
        )
    )

    envelope = SessionContextBuilder(store).build(
        session.id,
        current,
        permission_policy="ask",
        project_prompt="默认使用中文，并优先复用现有组件。",
    )

    assert envelope.current_request.content == "我刚才选择了什么？"
    assert envelope.run_ledger[0].review_status == "discarded"
    assert envelope.run_ledger[0].changes_applied_to_project is False
    assert envelope.run_ledger[0].approval_decisions == ["apply_patch:rejected:reject"]
    assert envelope.project_prompt == "默认使用中文，并优先复用现有组件。"
    assert "默认使用中文，并优先复用现有组件。" in envelope.to_prompt_text()
    assert "discarded" in envelope.to_prompt_text()


def test_restored_running_run_is_marked_stopped(tmp_path) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    snapshot = RunSnapshot(
        id="run-interrupted",
        status="running",
        review_status="pending",
        workspace_relative_path="runtime-data/runs/run-interrupted/todo-demo",
        session_id=session.id,
        intent=sample_brief(),
        approvals=[
            ToolApproval(
                id="approval-interrupted",
                tool_call_id="patch-1",
                tool_name="apply_patch",
                target="source.txt",
                reason="等待修改批准",
                patch="--- a/source.txt\n+++ b/source.txt\n",
                status="approval_required",
            )
        ],
        events=[],
        context_checkpoint=ContextCheckpoint(
            summary="重启前的上下文摘要",
            modified_files=["src/filter.ts"],
        ),
        metrics=RunMetrics(model_turns=2, tool_calls=1),
        history=[
            ModelTurn(action="修改筛选", reason="实现需求"),
            ToolResult(
                call_id="patch-1",
                tool_name="apply_patch",
                ok=True,
                summary="Updated src/filter.ts",
            ),
        ],
    )
    store.save_run(snapshot)
    manager = RunManager(tmp_path, snapshot_sink=store.save_run)

    restored = manager.restore(store.load_runs()[0])
    persisted = make_store(tmp_path / "intentflow.db").load_runs()[0]

    assert restored.status == "stopped"
    assert restored.events[-1].action == "服务重启，先前运行已停止"
    assert restored.approvals[0].status == "cancelled"
    assert restored.context_checkpoint.summary == "重启前的上下文摘要"
    assert restored.metrics.model_turns == 2
    assert len(restored.history) == 2
    assert persisted.status == "stopped"
    assert persisted.context_checkpoint.summary == "重启前的上下文摘要"
    assert len(persisted.history) == 2


async def test_delete_session_removes_history_and_run_workspace(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    store.add_message(session.id, "user", "ask", "介绍一下项目")
    store.add_canvas_snapshot(
        session.id,
        IntentCanvas(
            notes=[
                CanvasNote(
                    id="note-1",
                    text="说明",
                    position=CanvasPosition(x=0, y=0),
                )
            ]
        ),
    )
    run_root = tmp_path / "runtime-data" / "runs" / "run-delete"
    workspace = run_root / "todo-demo"
    workspace.mkdir(parents=True)
    (workspace / "result.txt").write_text("temporary", encoding="utf-8")
    snapshot = RunSnapshot(
        id="run-delete",
        status="completed",
        review_status="discarded",
        workspace_relative_path="runtime-data/runs/run-delete/todo-demo",
        session_id=session.id,
        intent=sample_brief(),
        events=[],
    )
    store.save_run(snapshot)
    manager = RunManager(tmp_path, snapshot_sink=store.save_run)
    manager.restore(snapshot)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.delete(f"/api/sessions/{session.id}")

    assert response.status_code == 204
    assert store.get_detail(session.id) is None
    assert store.load_runs() == []
    assert manager.get(snapshot.id) is None
    assert not run_root.exists()


async def test_delete_session_undoes_pending_direct_run_before_cleanup(
    tmp_path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    project_root = tmp_path / "examples" / "todo-demo"
    project_root.mkdir(parents=True)
    project_file = project_root / "source.txt"
    project_file.write_text("original", encoding="utf-8")
    checkpoint_root = tmp_path / "runtime-data" / "runs" / "run-direct-delete" / "checkpoint"
    checkpoint = RunCheckpoint(checkpoint_root, project_root)
    checkpoint.apply_text_change("source.txt", project_file, "agent change")
    snapshot = RunSnapshot(
        id="run-direct-delete",
        status="completed",
        review_status="pending",
        workspace_relative_path="runtime-data/runs/run-direct-delete/checkpoint",
        workspace_mode="direct",
        session_id=session.id,
        intent=sample_brief(),
        events=[],
    )
    store.save_run(snapshot)
    manager = RunManager(
        tmp_path,
        snapshot_sink=store.save_run,
        default_project_root=project_root,
    )
    manager.restore(snapshot)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.delete(f"/api/sessions/{session.id}")

    assert response.status_code == 204
    assert project_file.read_text(encoding="utf-8") == "original"
    assert store.get_detail(session.id) is None
    assert manager.get(snapshot.id) is None
    assert not checkpoint_root.parent.exists()


async def test_delete_session_rejects_running_agent(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    store.save_run(
        RunSnapshot(
            id="run-active",
            status="running",
            review_status="pending",
            workspace_relative_path="runtime-data/runs/run-active/todo-demo",
            session_id=session.id,
            intent=sample_brief(),
            events=[],
        )
    )
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "run_manager", RunManager(tmp_path))
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.delete(f"/api/sessions/{session.id}")

    assert response.status_code == 409
    assert store.get_detail(session.id) is not None


class StubResponder:
    async def answer(self, messages, canvas, project_context, session_context) -> str:
        assert messages[-1].content == "这个项目能做什么？"
        assert canvas is not None
        assert "Project:" in project_context
        assert "Authoritative IntentFlow session context" in session_context
        assert "默认使用中文，并优先复用现有组件。" in session_context
        return "这是一个可验证的 Todo Agent 示例。"


async def test_session_api_creates_and_restores_ask_messages(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "examples" / "todo-demo"
    project_root.mkdir(parents=True)
    store = make_store(tmp_path / "intentflow.db")
    registry = ProjectRegistry(tmp_path / "intentflow.db", tmp_path)
    project = registry.get("todo-demo")
    assert project is not None
    registry.update(
        project.id,
        name=project.name,
        test_command=project.test_command,
        build_command=project.build_command,
        ignored_names=project.ignored_names,
        prompt="默认使用中文，并优先复用现有组件。",
    )
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "project_registry", registry)
    monkeypatch.setattr(main_module, "create_conversation_responder", lambda: StubResponder())
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/sessions", json={"title": "新对话"})
        session_id = created.json()["id"]
        sent = await client.post(
            f"/api/sessions/{session_id}/messages",
            json={
                "content": "这个项目能做什么？",
                "mode": "ask",
                "attach_canvas": True,
                "canvas": {
                    "notes": [
                        {
                            "id": "note-1",
                            "text": "Todo 项目",
                            "label": None,
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "connections": [],
                    "supplemental_text": "",
                },
            },
        )
        restored = await client.get(f"/api/sessions/{session_id}")

    assert created.status_code == 201
    assert sent.status_code == 201
    assert sent.json()["run"] is None
    assert sent.json()["assistant_message"]["content"] == "这是一个可验证的 Todo Agent 示例。"
    assert len(restored.json()["messages"]) == 2
    assert len(restored.json()["canvas_snapshots"]) == 1


class StubCompiler:
    def __init__(self, expected_text: str = "先规划筛选功能") -> None:
        self.expected_text = expected_text

    async def compile(
        self,
        canvas: IntentCanvas,
        *,
        project_context: str = "",
    ) -> IntentBrief:
        assert any(note.text == self.expected_text for note in canvas.notes)
        assert project_context
        return sample_brief()

    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == self.expected_text
            for note in canvas.notes
        )
        assert project_context
        assert "Authoritative IntentFlow session context" in session_context
        return IntentRequestDecision(action="execute", brief=sample_brief())

    async def compile_plan_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == self.expected_text
            for note in canvas.notes
        )
        assert project_context
        assert "Authoritative IntentFlow session context" in session_context
        return IntentRequestDecision(
            action="propose",
            brief=sample_brief(),
            canvas=sample_plan_canvas(),
        )

    async def refine_plan(
        self,
        original: IntentBrief,
        canvas: IntentCanvas,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentBrief:
        assert project_context
        assert "Authoritative IntentFlow session context" in session_context
        behavior = next(note for note in canvas.notes if note.label == "behavior")
        acceptance = next(note for note in canvas.notes if note.label == "acceptance")
        return original.model_copy(
            update={
                "requirements": [
                    original.requirements[0].model_copy(
                        update={
                            "description": behavior.text,
                            "acceptance_criteria": [acceptance.text],
                            "source_ids": [behavior.id, acceptance.id],
                        }
                    )
                ]
            }
        )


class GreetingCompiler:
    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == "你好"
            for note in canvas.notes
        )
        assert any(note.text == "增加筛选功能" for note in canvas.notes)
        assert project_context
        assert "Authoritative IntentFlow session context" in session_context
        return IntentRequestDecision(
            action="answer",
            response="你好，请告诉我希望修改或验证的具体内容。",
        )


class ProjectQuestionCompiler:
    async def compile_plan_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == "我们这是一个什么项目"
            for note in canvas.notes
        )
        assert "Project:" in project_context
        assert "Authoritative IntentFlow session context" in session_context
        return IntentRequestDecision(
            action="answer",
            response="这是 IntentFlow 使用的 Todo 演示项目。",
        )


class TextPlanningCompiler:
    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == "先规划筛选功能"
            for note in canvas.notes
        )
        assert project_context
        assert "Authoritative IntentFlow session context" in session_context
        return IntentRequestDecision(
            action="answer",
            response="可以先从筛选状态和空状态反馈两部分考虑。",
        )

    async def compile_plan_request(self, *args: object, **kwargs: object) -> IntentRequestDecision:
        del args, kwargs
        raise AssertionError("关闭规划 Canvas 模式时不应调用 Canvas 规划")


class ReviewQuestionCompiler:
    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        assert any(
            note.id == primary_source_id and note.text == "我刚刚接受还是放弃了修改？"
            for note in canvas.notes
        )
        assert '"review_status": "discarded"' in session_context
        assert '"changes_applied_to_project": false' in session_context
        return IntentRequestDecision(action="answer", response="你刚刚放弃了修改。")


class BlockingCompiler:
    async def compile_agent_request(
        self,
        canvas: IntentCanvas,
        primary_source_id: str,
        *,
        project_context: str = "",
        session_context: str = "",
    ) -> IntentRequestDecision:
        await asyncio.Event().wait()
        raise AssertionError("cancelled model request unexpectedly resumed")


def test_project_context_contains_source_and_ignores_dependencies(tmp_path) -> None:
    project = tmp_path / "todo-demo"
    (project / "src").mkdir(parents=True)
    (project / "node_modules" / "package").mkdir(parents=True)
    (project / "src" / "main.js").write_text("export const ready = true;", encoding="utf-8")
    (project / "package.json").write_text('{"name":"todo-demo"}', encoding="utf-8")
    (project / "package-lock.json").write_text("ignored", encoding="utf-8")
    (project / "node_modules" / "package" / "index.js").write_text(
        "ignored",
        encoding="utf-8",
    )

    context = build_project_context(project)

    assert "src/main.js" in context
    assert "export const ready = true;" in context
    assert "package.json" in context
    assert "package-lock.json" not in context
    assert "node_modules" not in context


async def test_plan_message_returns_structured_intent_without_a_run(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path / "intentflow.db")
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "create_ai_intent_compiler", lambda: StubCompiler())
    session = store.create_session("todo-demo")
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={
                "content": "先规划筛选功能",
                "mode": "agent",
                "canvas_plan_mode": True,
            },
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["run"] is None
    assert payload["task_draft"]["status"] == "proposed"
    assert payload["task_draft"]["version"] == 1
    assert payload["task_draft"]["canvas"]["notes"][0]["text"] == "规划待办筛选"
    assert payload["task_draft"]["canvas"]["connections"][0]["label"] == "包含"
    assert payload["assistant_message"]["task_draft_id"] == payload["task_draft"]["id"]
    assert payload["assistant_message"]["intent"]["title"] == "增加筛选"
    assert payload["assistant_message"]["content"] == (
        "收到，我先根据当前项目整理了一份《增加筛选》计划。"
    )


async def test_plan_wording_cannot_trigger_canvas_when_mode_is_disabled(
    tmp_path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "intentflow.db")
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: TextPlanningCompiler(),
    )
    session = store.create_session("todo-demo")
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={"content": "先规划筛选功能", "mode": "agent"},
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["run"] is None
    assert payload["task_draft"] is None
    assert payload["assistant_message"]["content"] == (
        "可以先从筛选状态和空状态反馈两部分考虑。"
    )


async def test_plan_question_returns_direct_answer_without_intent(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path / "intentflow.db")
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: ProjectQuestionCompiler(),
    )
    session = store.create_session("todo-demo")
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={
                "content": "我们这是一个什么项目",
                "mode": "agent",
                "canvas_plan_mode": True,
            },
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["run"] is None
    assert payload["assistant_message"]["intent"] is None
    assert payload["assistant_message"]["content"] == "这是 IntentFlow 使用的 Todo 演示项目。"


async def test_unified_agent_receives_discarded_run_fact_for_a_follow_up(
    tmp_path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    store.save_run(
        RunSnapshot(
            id="run-discarded",
            status="completed",
            review_status="discarded",
            workspace_relative_path="runtime-data/runs/run-discarded/todo-demo",
            session_id=session.id,
            intent=sample_brief(),
            events=[],
            report=RunReport(status="completed", summary="代码修改已完成"),
        )
    )
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: ReviewQuestionCompiler(),
    )
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={"content": "我刚刚接受还是放弃了修改？"},
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["run"] is None
    assert payload["user_message"]["mode"] == "agent"
    assert payload["assistant_message"]["content"] == "你刚刚放弃了修改。"


async def test_message_processing_can_be_cancelled_from_the_session_endpoint(
    tmp_path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: BlockingCompiler(),
    )
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        send_task = asyncio.create_task(
            client.post(
                f"/api/sessions/{session.id}/messages",
                json={"content": "分析一下当前实现"},
            )
        )
        for _ in range(100):
            detail = store.get_detail(session.id)
            if session.id in main_module.active_message_tasks and detail and detail.messages:
                break
            await asyncio.sleep(0.01)
        detail_response = await client.get(f"/api/sessions/{session.id}")
        delete_response = await client.delete(f"/api/sessions/{session.id}")
        cancelled = await client.post(f"/api/sessions/{session.id}/cancel")
        response = await send_task

    restored = store.get_detail(session.id)
    assert detail_response.status_code == 200
    assert delete_response.status_code == 409
    assert cancelled.status_code == 200
    assert cancelled.json() == {"cancelled": True, "kind": "message"}
    assert response.status_code == 201
    assert response.json()["assistant_message"]["content"] == (
        "已中断本次处理，没有启动新的 Agent 运行。"
    )
    assert restored is not None
    assert len(restored.messages) == 2
    assert restored.runs == []


async def test_agent_message_requires_previous_run_review(tmp_path, monkeypatch) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    pending_run = RunSnapshot(
        id="run-pending-review",
        status="completed",
        review_status="pending",
        workspace_relative_path="runtime-data/runs/run-pending-review/todo-demo",
        session_id=session.id,
        intent=sample_brief(),
        events=[],
    )
    store.save_run(pending_run)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: StubCompiler("继续修改上一轮结果"),
    )
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={"content": "继续修改上一轮结果", "mode": "agent"},
        )

    restored = store.get_detail(session.id)
    assert response.status_code == 201
    assert "需要先保留修改或撤销本轮" in response.json()["assistant_message"]["content"]
    assert restored is not None
    assert len(restored.messages) == 2
    assert restored.runs[0].review_status == "pending"

    store.save_run(pending_run.model_copy(update={"review_status": "accepted"}))
    assert store.get_pending_review_run(session.id) is None


async def test_agent_greeting_with_canvas_replies_without_starting_run(
    tmp_path,
    monkeypatch,
) -> None:
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "create_ai_intent_compiler", lambda: GreetingCompiler())
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={
                "content": "你好",
                "mode": "agent",
                "attach_canvas": True,
                "canvas": {
                    "notes": [
                        {
                            "id": "canvas-task",
                            "text": "增加筛选功能",
                            "label": "behavior",
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "connections": [],
                    "supplemental_text": "",
                },
            },
        )

    payload = response.json()
    assert response.status_code == 201
    assert payload["run"] is None
    assert payload["assistant_message"]["content"] == "你好，请告诉我希望修改或验证的具体内容。"
    assert store.get_detail(session.id).runs == []


def agent_model_factory(_registry):
    return FakeModelClient(
        [
            ModelTurn(
                action="运行测试",
                reason="获取验证证据",
                related_requirement_ids=["REQ-01"],
                tool_calls=[
                    ToolCall(
                        id="test",
                        name="run_command",
                        arguments={"command": "test"},
                        related_requirement_ids=["REQ-01"],
                    )
                ],
            ),
            ModelTurn(
                action="报告结果",
                reason="测试已通过",
                related_requirement_ids=["REQ-01"],
                tool_calls=[
                    ToolCall(
                        id="report",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "筛选计划已验证",
                            "evidence": ["test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-01",
                                    "status": "verified",
                                    "summary": "测试通过",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )


def pending_patch_model_factory(_registry):
    return FakeModelClient(
        [
            ModelTurn(
                action="修改文件",
                reason="验证统一中断入口",
                related_requirement_ids=["REQ-01"],
                tool_calls=[
                    ToolCall(
                        id="patch",
                        name="apply_patch",
                        arguments={
                            "path": "source.txt",
                            "old_text": "ready",
                            "new_text": "changed",
                        },
                        related_requirement_ids=["REQ-01"],
                    )
                ],
            )
        ]
    )


async def test_session_cancel_endpoint_stops_a_running_agent(tmp_path, monkeypatch) -> None:
    project = tmp_path / "examples" / "todo-demo"
    project.mkdir(parents=True)
    (project / "source.txt").write_text("ready", encoding="utf-8")
    store = make_store(tmp_path / "intentflow.db")
    session = store.create_session("todo-demo")
    manager = RunManager(
        tmp_path,
        model_client_factory=pending_patch_model_factory,
        command_factory=lambda _workspace: {},
        snapshot_sink=store.save_run,
        default_project_root=project,
    )
    snapshot = manager.start(sample_brief(), session_id=session.id)
    for _ in range(100):
        record = manager.get(snapshot.id)
        if record and record.approvals:
            break
        await asyncio.sleep(0.01)

    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(f"/api/sessions/{session.id}/cancel")

    record = manager.get(snapshot.id)
    assert response.status_code == 200
    assert response.json() == {"cancelled": True, "kind": "run"}
    assert record is not None
    assert record.status == "stopped"
    assert record.approvals[0].status == "cancelled"
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "ready"


async def test_agent_message_links_and_persists_its_run(tmp_path, monkeypatch) -> None:
    project = tmp_path / "examples" / "todo-demo"
    project.mkdir(parents=True)
    (project / "source.txt").write_text("ready", encoding="utf-8")
    database = tmp_path / "intentflow.db"
    store = make_store(database)
    registry = ProjectRegistry(database, tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=agent_model_factory,
        command_factory=lambda _workspace: {
            "test": (sys.executable, "-c", "print('ok')"),
        },
        snapshot_sink=store.save_run,
        project_resolver=registry.get,
    )
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "project_registry", registry)
    monkeypatch.setattr(main_module, "run_manager", manager)
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: StubCompiler("实现筛选功能"),
    )
    session = store.create_session("todo-demo")
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={"content": "实现筛选功能", "approval_mode": "auto"},
        )
        run_id = response.json()["run"]["id"]
        for _ in range(100):
            if manager.get(run_id).status != "running":
                break
            await asyncio.sleep(0.01)

    restored = make_store(tmp_path / "intentflow.db").get_detail(session.id)

    assert response.status_code == 201
    assert response.json()["user_message"]["mode"] == "agent"
    assert response.json()["run"]["approval_mode"] == "auto"
    assert response.json()["run"]["project_id"] == "todo-demo"
    assert response.json()["task_draft"]["status"] == "confirmed"
    assert response.json()["run"]["task_draft_id"] == response.json()["task_draft"]["id"]
    assert response.json()["assistant_message"]["task_draft_id"] == (
        response.json()["task_draft"]["id"]
    )
    assert response.json()["assistant_message"]["content"].startswith("收到，我会处理")
    assert response.json()["user_message"]["run_id"] == run_id
    assert restored is not None
    assert [message.run_id for message in restored.messages] == [run_id, run_id]
    assert restored.runs[0].status == "completed"
    assert restored.runs[0].trigger_message_id == restored.messages[0].id
    assert restored.runs[0].task_draft_id == restored.task_drafts[0].id
    assert restored.runs[0].context_checkpoint is not None
    assert restored.session.approval_mode == "auto"
    assert restored.runs[0].metrics.model_turns == 2
    assert len(restored.runs[0].history) == 4


async def test_confirmed_canvas_creates_a_new_draft_version_and_run(tmp_path, monkeypatch) -> None:
    project = tmp_path / "examples" / "todo-demo"
    project.mkdir(parents=True)
    (project / "source.txt").write_text("ready", encoding="utf-8")
    database = tmp_path / "intentflow.db"
    store = make_store(database)
    registry = ProjectRegistry(database, tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=agent_model_factory,
        command_factory=lambda _workspace: {
            "test": (sys.executable, "-c", "print('ok')"),
        },
        snapshot_sink=store.save_run,
        project_resolver=registry.get,
    )
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "project_registry", registry)
    monkeypatch.setattr(main_module, "run_manager", manager)
    monkeypatch.setattr(main_module, "create_ai_intent_compiler", lambda: StubCompiler())
    session = store.create_session("todo-demo")
    source_message = store.add_message(session.id, "user", "plan", "先规划筛选功能")
    proposal = store.add_task_draft(
        session.id,
        source_message.id,
        sample_brief(),
        status="proposed",
    )
    confirmed_canvas = sample_plan_canvas().model_dump()
    confirmed_canvas["notes"][1]["text"] = "确认后的筛选需求"
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.id}/messages",
            json={
                "content": "确认并执行任务草案",
                "approval_mode": "auto",
                "attach_canvas": True,
                "canvas": confirmed_canvas,
                "task_draft_id": proposal.id,
            },
        )
        run_id = response.json()["run"]["id"]
        for _ in range(100):
            if manager.get(run_id).status != "running":
                break
            await asyncio.sleep(0.01)

    payload = response.json()
    restored = store.get_detail(session.id)
    assert response.status_code == 201
    assert payload["task_draft"]["version"] == 2
    assert payload["task_draft"]["status"] == "confirmed"
    assert payload["task_draft"]["parent_id"] == proposal.id
    assert payload["run"]["task_draft_id"] == payload["task_draft"]["id"]
    assert payload["run"]["intent"]["requirements"][0]["description"] == "确认后的筛选需求"
    assert payload["run"]["intent"]["requirements"][0]["acceptance_criteria"] == ["筛选结果正确"]
    assert restored is not None
    assert len(restored.task_drafts) == 2
    assert restored.task_drafts[-1].canvas is not None
    assert any(
        note.text == "确认后的筛选需求"
        for note in restored.task_drafts[-1].canvas.notes
    )
