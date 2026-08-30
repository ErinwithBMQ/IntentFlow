import asyncio
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.agent.model_client import FakeModelClient
from app.agent.models import IntentBrief, IntentRequirement, ModelTurn, ToolCall
from app.runs import RunManager


def make_repository(root: Path) -> None:
    demo = root / "examples" / "todo-demo"
    demo.mkdir(parents=True)
    (demo / "source.txt").write_text("original", encoding="utf-8")


def fake_model_factory(_registry):
    return FakeModelClient(
        [
            ModelTurn(
                action="检查目标文件",
                reason="确认临时工作区可以读取",
                tool_calls=[
                    ToolCall(
                        id="read",
                        name="read_file",
                        arguments={"path": "source.txt"},
                    )
                ],
            ),
            ModelTurn(
                action="运行验证",
                reason="提供真实命令证据",
                tool_calls=[
                    ToolCall(
                        id="test",
                        name="run_command",
                        arguments={"command": "test"},
                        related_requirement_ids=["REQ-1"],
                    )
                ],
            ),
            ModelTurn(
                action="提交结果",
                reason="验证已经通过",
                tool_calls=[
                    ToolCall(
                        id="report",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "临时副本已验证",
                            "evidence": ["test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "测试命令已通过",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )


def ninth_turn_report_model_factory(_registry):
    inspection_turns = [
        ModelTurn(
            action=f"检查项目文件 {index}",
            reason="在提交结果前完成必要检查",
            related_requirement_ids=["REQ-1"],
            tool_calls=[
                ToolCall(
                    id=f"read-{index}",
                    name="read_file",
                    arguments={"path": "source.txt"},
                )
            ],
        )
        for index in range(1, 8)
    ]
    return FakeModelClient(
        [
            *inspection_turns,
            ModelTurn(
                action="运行第八轮验证",
                reason="实现完成后获取真实验证证据",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="test-on-eight",
                        name="run_command",
                        arguments={"command": "test"},
                    )
                ],
            ),
            ModelTurn(
                action="在第九轮提交结果",
                reason="验证已经通过",
                tool_calls=[
                    ToolCall(
                        id="report-on-nine",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "九轮任务已完成",
                            "evidence": ["test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "第八轮测试通过",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )


def command_factory(_workspace: Path) -> dict[str, tuple[str, ...]]:
    return {"test": (sys.executable, "-c", "print('ok')")}


def modifying_model_factory(_registry):
    return FakeModelClient(
        [
            ModelTurn(
                action="修改目标文件",
                reason="把示例内容更新为 approved",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="patch",
                        name="apply_patch",
                        arguments={
                            "path": "source.txt",
                            "old_text": "original",
                            "new_text": "approved",
                        },
                    )
                ],
            ),
            ModelTurn(
                action="运行验证",
                reason="确认修改后的项目可验证",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(id="test", name="run_command", arguments={"command": "test"})
                ],
            ),
            ModelTurn(
                action="提交结果",
                reason="修改已经验证",
                tool_calls=[
                    ToolCall(
                        id="report",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "修改完成",
                            "evidence": ["test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "修改已经通过测试",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )


def two_patch_model_factory(_registry):
    return FakeModelClient(
        [
            ModelTurn(
                action="第一次修改",
                reason="先更新为 intermediate",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="patch-1",
                        name="apply_patch",
                        arguments={
                            "path": "source.txt",
                            "old_text": "original",
                            "new_text": "intermediate",
                        },
                    )
                ],
            ),
            ModelTurn(
                action="第二次修改",
                reason="完成目标内容",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="patch-2",
                        name="apply_patch",
                        arguments={
                            "path": "source.txt",
                            "old_text": "intermediate",
                            "new_text": "approved",
                        },
                    )
                ],
            ),
            ModelTurn(
                action="运行验证",
                reason="确认两次修改后的结果",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(id="test", name="run_command", arguments={"command": "test"})
                ],
            ),
            ModelTurn(
                action="提交结果",
                reason="修改已经验证",
                tool_calls=[
                    ToolCall(
                        id="report",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "两次修改完成",
                            "evidence": ["test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "修改已经通过测试",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )


async def wait_until_finished(manager: RunManager, run_id: str) -> None:
    for _ in range(100):
        record = manager.get(run_id)
        if record is not None and record.status != "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish")


async def wait_for_approval(manager: RunManager, run_id: str) -> str:
    for _ in range(100):
        record = manager.get(run_id)
        if record is not None:
            pending = next(
                (
                    approval
                    for approval in record.approvals
                    if approval.status == "approval_required"
                ),
                None,
            )
            if pending is not None:
                return pending.id
        await asyncio.sleep(0.01)
    raise AssertionError("approval was not requested")


def run_payload() -> dict[str, object]:
    return {
        "intent": {
            "title": "修改示例",
            "goal": "更新文件并验证",
            "requirements": [
                {
                    "id": "REQ-1",
                    "description": "更新文件",
                    "acceptance_criteria": ["测试通过"],
                    "source_ids": ["note-1"],
                }
            ],
            "constraints": [],
        }
    }


async def test_apply_patch_waits_for_approval_and_rejects_duplicate_response(
    tmp_path,
    monkeypatch,
) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=modifying_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=run_payload())
        run_id = created.json()["id"]
        approval_id = await wait_for_approval(manager, run_id)
        recoverable = await client.get(f"/api/runs/{run_id}")
        record = manager.get(run_id)
        assert record is not None
        assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "original"
        approval = record.approvals[0]
        assert "-original" in approval.patch
        assert "+approved" in approval.patch

        approved = await client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"decision": "allow_once"},
        )
        duplicate = await client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"decision": "allow_once"},
        )
        await wait_until_finished(manager, run_id)
        changes = await client.get(f"/api/runs/{run_id}/changes")

    assert recoverable.json()["approvals"][0]["id"] == approval_id
    assert approved.status_code == 200
    assert approved.json()["approvals"][0]["status"] == "approved"
    assert duplicate.status_code == 409
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "approved"
    assert record.status == "completed"
    assert record.report.requirement_results[0].status == "verified"
    assert changes.json()["changed_files"] == 1


async def test_stop_cancels_pending_approval_without_applying_patch(tmp_path, monkeypatch) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=modifying_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=run_payload())
        run_id = created.json()["id"]
        await wait_for_approval(manager, run_id)
        stopped = await client.post(f"/api/runs/{run_id}/stop")
        await wait_until_finished(manager, run_id)

    record = manager.get(run_id)
    assert record is not None
    assert stopped.status_code == 200
    assert record.status == "stopped"
    assert record.approvals[0].status == "cancelled"
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "original"


async def test_allow_for_run_automatically_approves_later_patches(tmp_path, monkeypatch) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=two_patch_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=run_payload())
        run_id = created.json()["id"]
        approval_id = await wait_for_approval(manager, run_id)
        response = await client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"decision": "allow_for_run"},
        )
        await wait_until_finished(manager, run_id)

    record = manager.get(run_id)
    assert record is not None
    assert response.status_code == 200
    assert record.approval_mode == "auto"
    assert [approval.status for approval in record.approvals] == ["approved", "approved"]
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "approved"
    required_events = [event for event in record.events if event.kind == "approval_required"]
    assert len(required_events) == 1


async def test_run_can_start_with_automatic_approval_policy(tmp_path) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=modifying_model_factory,
        command_factory=command_factory,
    )

    snapshot = manager.start(
        IntentBrief.model_validate(run_payload()["intent"]),
        approval_mode="auto",
    )
    await wait_until_finished(manager, snapshot.id)

    record = manager.get(snapshot.id)
    assert record is not None
    assert record.approval_mode == "auto"
    assert record.approvals[0].status == "approved"
    assert not [event for event in record.events if event.kind == "approval_required"]
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "approved"


async def test_rejected_patch_is_returned_to_model_without_changing_file(
    tmp_path,
    monkeypatch,
) -> None:
    make_repository(tmp_path)
    created_models: list[FakeModelClient] = []

    def rejecting_model_factory(_registry):
        model = FakeModelClient(
            [
                ModelTurn(
                    action="请求修改",
                    reason="尝试更新目标文件",
                    related_requirement_ids=["REQ-1"],
                    tool_calls=[
                        ToolCall(
                            id="patch",
                            name="apply_patch",
                            arguments={
                                "path": "source.txt",
                                "old_text": "original",
                                "new_text": "rejected",
                            },
                        )
                    ],
                ),
                ModelTurn(
                    action="报告拒绝结果",
                    reason="用户没有允许修改",
                    tool_calls=[
                        ToolCall(
                            id="report",
                            name="report_result",
                            arguments={
                                "status": "failed",
                                "summary": "修改被用户拒绝",
                                "requirements": [
                                    {
                                        "requirement_id": "REQ-1",
                                        "status": "unresolved",
                                        "summary": "用户拒绝了文件修改",
                                    }
                                ],
                            },
                        )
                    ],
                ),
            ]
        )
        created_models.append(model)
        return model

    manager = RunManager(
        tmp_path,
        model_client_factory=rejecting_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=run_payload())
        run_id = created.json()["id"]
        approval_id = await wait_for_approval(manager, run_id)
        rejected = await client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"decision": "reject"},
        )
        await wait_until_finished(manager, run_id)

    record = manager.get(run_id)
    assert record is not None
    rejected_result = created_models[0].received_histories[1][-1]
    assert rejected.status_code == 200
    assert rejected_result.ok is False
    assert "User rejected" in rejected_result.summary
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "original"


async def test_pending_approval_times_out_without_applying_patch(tmp_path) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=modifying_model_factory,
        command_factory=command_factory,
        approval_timeout_seconds=0.01,
    )
    snapshot = manager.start(IntentBrief.model_validate(run_payload()["intent"]))

    await wait_until_finished(manager, snapshot.id)

    record = manager.get(snapshot.id)
    assert record is not None
    assert record.status == "stopped"
    assert record.approvals[0].status == "cancelled"
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "original"


async def test_run_api_copies_demo_and_streams_events(tmp_path, monkeypatch) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=fake_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    payload = {
        "intent": {
            "title": "验证 Todo",
            "goal": "确认 Agent API 闭环",
            "requirements": [
                {
                    "id": "REQ-1",
                    "description": "运行验证",
                    "acceptance_criteria": ["测试通过"],
                    "source_ids": ["note-1"],
                }
            ],
            "constraints": [],
        }
    }
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=payload)
        assert created.status_code == 201
        run_id = created.json()["id"]
        workspace = tmp_path / created.json()["workspace_relative_path"]
        record = manager.get(run_id)
        assert record is not None
        assert record.baseline != record.workspace
        assert record.baseline.relative_to(tmp_path).as_posix() == (
            f"runtime-data/runs/{run_id}/baseline/todo-demo"
        )
        assert (record.baseline / "source.txt").read_text(encoding="utf-8") == "original"
        assert (workspace / "source.txt").read_text(encoding="utf-8") == "original"
        assert (tmp_path / "examples" / "todo-demo" / "source.txt").read_text() == "original"

        await wait_until_finished(manager, run_id)
        snapshot = await client.get(f"/api/runs/{run_id}")
        assert snapshot.json()["status"] == "completed"
        assert snapshot.json()["report"]["evidence"] == ["test exited with code 0"]
        requirement = snapshot.json()["report"]["requirement_results"][0]
        assert requirement["requirement_id"] == "REQ-1"
        assert requirement["status"] == "verified"
        assert requirement["evidence"] == ["test exited with code 0"]

        events = await client.get(f"/api/runs/{run_id}/events")
        assert events.status_code == 200
        assert "event: run_event" in events.text
        assert '"kind":"run_started"' in events.text
        assert '"kind":"run_finished"' in events.text


async def test_run_api_rejects_unknown_run() -> None:
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/runs/missing")
    assert response.status_code == 404


async def test_run_baseline_stays_frozen_when_the_project_changes(tmp_path) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=fake_model_factory,
        command_factory=command_factory,
    )
    snapshot = manager.start(
        IntentBrief(
            title="固定 Diff 基准",
            goal="确认运行后的项目变化不会影响本次基准",
            requirements=[
                IntentRequirement(
                    id="REQ-1",
                    description="保留运行开始时的代码",
                    acceptance_criteria=["基准内容保持不变"],
                    source_ids=["note-1"],
                )
            ],
        )
    )
    record = manager.get(snapshot.id)
    assert record is not None

    project_file = tmp_path / "examples" / "todo-demo" / "source.txt"
    project_file.write_text("changed later", encoding="utf-8")
    await wait_until_finished(manager, snapshot.id)

    assert project_file.read_text(encoding="utf-8") == "changed later"
    assert (record.baseline / "source.txt").read_text(encoding="utf-8") == "original"
    assert (record.workspace / "source.txt").read_text(encoding="utf-8") == "original"


async def test_run_api_allows_a_ninth_turn_for_the_final_report(
    tmp_path,
    monkeypatch,
) -> None:
    make_repository(tmp_path)
    manager = RunManager(
        tmp_path,
        model_client_factory=ninth_turn_report_model_factory,
        command_factory=command_factory,
    )
    monkeypatch.setattr(main_module, "run_manager", manager)
    payload = {
        "intent": {
            "title": "验证运行预算",
            "goal": "第八轮验证后在第九轮报告",
            "requirements": [
                {
                    "id": "REQ-1",
                    "description": "允许第九轮提交报告",
                    "acceptance_criteria": ["最终状态为 completed"],
                    "source_ids": ["note-1"],
                }
            ],
            "constraints": [],
        }
    }

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/runs", json=payload)
        assert created.status_code == 201
        run_id = created.json()["id"]
        await wait_until_finished(manager, run_id)
        snapshot = await client.get(f"/api/runs/{run_id}")

    assert snapshot.json()["status"] == "completed"
    assert snapshot.json()["report"]["summary"] == "九轮任务已完成"
    assert snapshot.json()["report"]["requirement_results"][0]["status"] == "verified"
