import asyncio
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.agent.model_client import FakeModelClient
from app.agent.models import ModelTurn, ToolCall
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


def command_factory(_workspace: Path) -> dict[str, tuple[str, ...]]:
    return {"test": (sys.executable, "-c", "print('ok')")}


async def wait_until_finished(manager: RunManager, run_id: str) -> None:
    for _ in range(100):
        record = manager.get(run_id)
        if record is not None and record.status != "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("run did not finish")


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
