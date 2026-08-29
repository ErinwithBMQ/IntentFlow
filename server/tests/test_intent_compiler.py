import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.agent.models import IntentBrief, IntentRequirement
from app.intent.compiler import AIIntentCompiler, IntentCompileError, compile_canvas
from app.intent.models import CanvasConnection, CanvasNote, CanvasPosition, IntentCanvas
from app.main import app


class FakeResponsesAPI:
    def __init__(
        self,
        arguments: dict[str, object] | list[dict[str, object] | str],
        tool_name: str = "submit_intent_brief",
    ) -> None:
        self.arguments = arguments if isinstance(arguments, list) else [arguments]
        self.tool_name = tool_name
        self.requests: list[dict[str, object]] = []

    async def create(self, **request: object) -> object:
        self.requests.append(request)
        arguments = self.arguments.pop(0) if len(self.arguments) > 1 else self.arguments[0]
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name=self.tool_name,
                    arguments=(
                        arguments
                        if isinstance(arguments, str)
                        else json.dumps(arguments, ensure_ascii=False)
                    ),
                )
            ]
        )


class FakeOpenAIClient:
    def __init__(
        self,
        arguments: dict[str, object] | list[dict[str, object] | str],
        tool_name: str = "submit_intent_brief",
    ) -> None:
        self.responses = FakeResponsesAPI(arguments, tool_name)


class StubIntentCompiler:
    def __init__(self, brief: IntentBrief) -> None:
        self.brief = brief

    async def compile(self, canvas: IntentCanvas) -> IntentBrief:
        del canvas
        return self.brief


def note(note_id: str, text: str, label: str | None = None) -> CanvasNote:
    return CanvasNote(
        id=note_id,
        text=text,
        label=label,
        position=CanvasPosition(x=0, y=0),
    )


def test_compiler_keeps_requirements_traceable_to_canvas_notes() -> None:
    canvas = IntentCanvas(
        notes=[
            note("idea-1", "让用户快速添加待办", "idea"),
            note("behavior-1", "提交文字后立即显示新任务", "behavior"),
            note("acceptance-1", "空白输入不会创建任务", "acceptance"),
            note("constraint-1", "保持当前页面风格", "constraint"),
        ],
        connections=[
            CanvasConnection(
                id="edge-1",
                source="behavior-1",
                target="acceptance-1",
                label="同时保证",
            )
        ],
        supplemental_text="优先保证演示稳定",
    )

    brief = compile_canvas(canvas)

    assert brief.goal == "让用户快速添加待办"
    assert len(brief.requirements) == 1
    assert brief.requirements[0].source_ids == ["behavior-1", "acceptance-1"]
    assert brief.requirements[0].acceptance_criteria == ["空白输入不会创建任务"]
    assert brief.constraints == ["保持当前页面风格", "补充说明：优先保证演示稳定"]


async def test_ai_compiler_uses_function_call_and_accepts_unconnected_notes() -> None:
    canvas = IntentCanvas(
        notes=[
            note("note-add", "提交文字后显示任务"),
            note("note-empty", "空白内容不能提交"),
        ]
    )
    fake_client = FakeOpenAIClient(
        {
            "title": "添加待办",
            "goal": "允许用户添加有效待办",
            "requirements": [
                {
                    "id": "REQ-01",
                    "description": "提交非空文字后显示任务",
                    "acceptance_criteria": ["新任务立即出现在列表中"],
                    "source_ids": ["note-add"],
                },
                {
                    "id": "REQ-02",
                    "description": "拒绝空白内容",
                    "acceptance_criteria": ["空白提交不会创建任务"],
                    "source_ids": ["note-empty"],
                },
            ],
            "constraints": [],
        }
    )
    compiler = AIIntentCompiler("test-model", client=fake_client)

    brief = await compiler.compile(
        canvas,
        project_context="--- src/main.js ---\nexport const tasks = [];",
    )

    assert [requirement.id for requirement in brief.requirements] == ["REQ-01", "REQ-02"]
    request = fake_client.responses.requests[0]
    assert "tool_choice" not in request
    assert request["tools"][0]["name"] == "submit_intent_brief"
    assert "note-add" in request["input"][0]["content"]
    assert "src/main.js" in request["input"][0]["content"]


async def test_ai_compiler_allows_supplemental_text_without_source_note() -> None:
    canvas = IntentCanvas(supplemental_text="增加一个清空全部待办的按钮")
    fake_client = FakeOpenAIClient(
        {
            "title": "清空待办",
            "goal": "一次清空全部待办",
            "requirements": [
                {
                    "id": "REQ-01",
                    "description": "点击按钮后清空列表",
                    "acceptance_criteria": ["列表中的任务数量变为零"],
                    "source_ids": [],
                }
            ],
            "constraints": [],
        }
    )

    brief = await AIIntentCompiler("test-model", client=fake_client).compile(canvas)

    assert brief.requirements[0].source_ids == []


async def test_agent_request_can_reply_without_running_when_latest_message_is_greeting() -> None:
    canvas = IntentCanvas(
        notes=[
            note("canvas-task", "增加筛选功能", "behavior"),
            note("message-1", "你好", "idea"),
        ]
    )
    fake_client = FakeOpenAIClient(
        {"message": "你好，请告诉我这次希望修改或验证什么。"},
        tool_name="respond_to_user",
    )

    decision = await AIIntentCompiler(
        "test-model",
        client=fake_client,
    ).compile_agent_request(
        canvas,
        "message-1",
        project_context="--- src/main.js ---\nexport const tasks = [];",
    )

    assert decision.brief is None
    assert decision.response == "你好，请告诉我这次希望修改或验证什么。"
    request = fake_client.responses.requests[0]
    assert [tool["name"] for tool in request["tools"]] == [
        "submit_intent_brief",
        "respond_to_user",
    ]
    assert "message-1" in request["input"][0]["content"]
    assert "src/main.js" in request["input"][0]["content"]


async def test_plan_request_answers_project_question_without_manufacturing_a_plan() -> None:
    canvas = IntentCanvas(notes=[note("message-1", "我们这是一个什么项目", "idea")])
    fake_client = FakeOpenAIClient(
        {"message": "这是 IntentFlow 使用的 Todo 演示项目。"},
        tool_name="respond_to_user",
    )

    decision = await AIIntentCompiler(
        "test-model",
        client=fake_client,
    ).compile_plan_request(
        canvas,
        "message-1",
        project_context="Project: todo-demo",
    )

    assert decision.brief is None
    assert decision.response == "这是 IntentFlow 使用的 Todo 演示项目。"
    request = fake_client.responses.requests[0]
    assert "must not turn a question into a plan" in request["instructions"]


async def test_ai_compiler_rejects_an_invented_source_id() -> None:
    canvas = IntentCanvas(notes=[note("real-note", "增加任务")])
    fake_client = FakeOpenAIClient(
        {
            "title": "增加任务",
            "goal": "增加任务",
            "requirements": [
                {
                    "id": "REQ-01",
                    "description": "增加任务",
                    "acceptance_criteria": ["任务出现在列表中"],
                    "source_ids": ["invented-note"],
                }
            ],
            "constraints": [],
        }
    )

    with pytest.raises(IntentCompileError, match="不存在的来源便签"):
        await AIIntentCompiler("test-model", client=fake_client).compile(canvas)


async def test_ai_compiler_retries_one_invalid_structured_result() -> None:
    canvas = IntentCanvas(supplemental_text="增加清空全部待办的按钮")
    valid_result = {
        "title": "清空待办",
        "goal": "一次清空全部待办",
        "requirements": [
            {
                "id": "REQ-01",
                "description": "点击按钮后清空列表",
                "acceptance_criteria": ["列表中的任务数量变为零"],
                "source_ids": [],
            }
        ],
        "constraints": [],
    }
    fake_client = FakeOpenAIClient(["{invalid json", valid_result])

    brief = await AIIntentCompiler("test-model", client=fake_client).compile(canvas)

    assert brief.title == "清空待办"
    assert len(fake_client.responses.requests) == 2
    retry_input = fake_client.responses.requests[1]["input"][0]["content"]
    assert "previous result failed validation" in retry_input


async def test_compile_endpoint_rejects_an_empty_canvas() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/intent/compile",
            json={"canvas": {"notes": [], "connections": [], "supplemental_text": ""}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Canvas needs at least one note or supplemental description"


async def test_compile_endpoint_uses_ai_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    brief = IntentBrief(
        title="显示任务",
        goal="提交后显示任务",
        requirements=[
            IntentRequirement(
                id="REQ-01",
                description="提交后显示任务",
                acceptance_criteria=["任务出现在列表中"],
                source_ids=["note-1"],
            )
        ],
    )
    monkeypatch.setattr(
        main_module,
        "create_ai_intent_compiler",
        lambda: StubIntentCompiler(brief),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/intent/compile",
            json={
                "canvas": {
                    "notes": [
                        {
                            "id": "note-1",
                            "text": "提交后显示任务",
                            "label": None,
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "connections": [],
                    "supplemental_text": "",
                }
            },
        )

    assert response.status_code == 200
    assert response.json()["compiler"] == "ai"
    assert "真实模型" in response.json()["notice"]


async def test_compile_endpoint_only_uses_local_compiler_when_requested() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/intent/compile",
            json={
                "compiler": "local",
                "canvas": {
                    "notes": [
                        {
                            "id": "note-1",
                            "text": "提交后显示任务",
                            "label": None,
                            "position": {"x": 0, "y": 0},
                        }
                    ],
                    "connections": [],
                    "supplemental_text": "",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["compiler"] == "local"
    assert "主动选择" in response.json()["notice"]
    assert response.json()["brief"]["requirements"][0]["source_ids"] == ["note-1"]
