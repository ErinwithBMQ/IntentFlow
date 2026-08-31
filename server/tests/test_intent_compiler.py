import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.agent.models import IntentBrief, IntentRequirement
from app.intent.compiler import (
    AIIntentCompiler,
    IntentCompileError,
    compile_canvas,
    validate_generated_canvas,
)
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


def test_generated_canvas_accepts_flexible_branches_with_compact_cards() -> None:
    brief = IntentBrief(
        title="提升可玩性",
        goal="提升 2048 的长期可玩性",
        requirements=[
            IntentRequirement(
                id="REQ-01",
                description="保存最高分",
                acceptance_criteria=["刷新页面后最高分仍然保留"],
            ),
            IntentRequirement(
                id="REQ-02",
                description="增加挑战模式",
                acceptance_criteria=["玩家可以切换并完成挑战模式"],
            ),
        ],
        constraints=["保留经典模式"],
    )
    canvas = IntentCanvas(
        notes=[
            note("goal", "提升 2048 可玩性", "idea"),
            note("high-score", "保存最高分", "behavior"),
            note("challenge", "增加挑战模式", "behavior"),
            note("classic", "保留经典模式", "constraint"),
            note("persisted", "刷新后记录仍保留", "acceptance"),
            note("switchable", "挑战模式可正常切换", "acceptance"),
        ],
        connections=[
            CanvasConnection(id="e1", source="goal", target="high-score", label="包含"),
            CanvasConnection(id="e2", source="goal", target="challenge", label="包含"),
            CanvasConnection(id="e3", source="high-score", target="persisted", label="验收"),
            CanvasConnection(id="e4", source="challenge", target="classic", label="保留"),
            CanvasConnection(id="e5", source="challenge", target="switchable", label="验收"),
        ],
    )

    validate_generated_canvas(canvas, brief)


def test_generated_canvas_rejects_an_overloaded_card_instead_of_truncating_it() -> None:
    canvas = IntentCanvas(
        notes=[
            note("goal", "提升代码编辑体验", "idea"),
            note(
                "behavior",
                "需要修改编辑器状态管理并同步处理保存冲突以及各种异常情况下的恢复行为",
                "behavior",
            ),
            note("acceptance", "修改后可以立即保存", "acceptance"),
        ]
    )

    with pytest.raises(IntentCompileError, match="信息过多"):
        validate_generated_canvas(canvas)


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
    assert decision.action == "answer"
    assert decision.response == "你好，请告诉我这次希望修改或验证什么。"
    request = fake_client.responses.requests[0]
    assert [tool["name"] for tool in request["tools"]] == [
        "submit_intent_brief",
        "respond_to_user",
    ]
    assert "explicit UI mode" in request["instructions"]
    assert "message-1" in request["input"][0]["content"]
    assert "src/main.js" in request["input"][0]["content"]


async def test_canvas_plan_request_returns_a_visual_plan() -> None:
    canvas = IntentCanvas(notes=[note("message-1", "先规划筛选功能", "idea")])
    fake_client = FakeOpenAIClient(
        {
            "title": "规划筛选",
            "goal": "规划待办筛选功能",
            "requirements": [
                {
                    "id": "REQ-01",
                    "description": "设计筛选交互",
                    "acceptance_criteria": ["给出可执行的实现步骤"],
                    "source_ids": ["message-1"],
                }
            ],
            "constraints": [],
            "canvas": {
                "notes": [
                    {
                        "id": "goal",
                        "text": "规划待办筛选",
                        "label": "idea",
                    },
                    {
                        "id": "filter",
                        "text": "设计筛选交互",
                        "label": "behavior",
                    },
                    {
                        "id": "count",
                        "text": "显示筛选数量",
                        "label": "behavior",
                    },
                    {
                        "id": "check",
                        "text": "筛选结果可验证",
                        "label": "acceptance",
                    },
                ],
                "connections": [
                    {"id": "e1", "source": "goal", "target": "filter", "label": "包含"},
                    {"id": "e2", "source": "goal", "target": "count", "label": "包含"},
                    {"id": "e3", "source": "filter", "target": "check", "label": "验收"},
                ],
            },
        },
        tool_name="submit_plan",
    )

    decision = await AIIntentCompiler(
        "test-model",
        client=fake_client,
    ).compile_plan_request(
        canvas,
        "message-1",
        session_context='{"review_status":"discarded"}',
    )

    assert decision.action == "propose"
    assert decision.brief is not None
    assert decision.brief.title == "规划筛选"
    assert decision.canvas is not None
    assert [note.text for note in decision.canvas.notes] == [
        "规划待办筛选",
        "设计筛选交互",
        "显示筛选数量",
        "筛选结果可验证",
    ]
    position_by_id = {note.id: note.position for note in decision.canvas.notes}
    assert position_by_id["goal"].x < position_by_id["filter"].x
    assert position_by_id["filter"].x == position_by_id["count"].x
    assert position_by_id["filter"].y != position_by_id["count"].y
    assert position_by_id["filter"].x < position_by_id["check"].x
    assert "discarded" in fake_client.responses.requests[0]["input"][0]["content"]
    assert [tool["name"] for tool in fake_client.responses.requests[0]["tools"]] == [
        "submit_plan",
        "respond_to_user",
    ]


async def test_refine_plan_combines_original_details_with_edited_canvas() -> None:
    original = IntentBrief(
        title="增加筛选",
        goal="让用户更快找到待办",
        requirements=[
            IntentRequirement(
                id="REQ-01",
                description="增加状态筛选",
                acceptance_criteria=["支持查看全部、未完成和已完成任务"],
                source_ids=["message-1"],
            )
        ],
        constraints=["保留现有任务数据"],
    )
    edited_canvas = IntentCanvas(
        notes=[
            note("goal", "快速找到待办", "idea"),
            note("filter", "只做未完成筛选", "behavior"),
            note("compatibility", "保留现有任务数据", "constraint"),
            note("check", "筛选结果准确", "acceptance"),
        ],
        connections=[
            CanvasConnection(id="e1", source="goal", target="filter", label="包含"),
            CanvasConnection(id="e2", source="filter", target="compatibility", label="约束"),
            CanvasConnection(id="e3", source="filter", target="check", label="验收"),
        ],
    )
    fake_client = FakeOpenAIClient(
        {
            "title": "增加未完成筛选",
            "goal": "让用户快速查看未完成待办",
            "requirements": [
                {
                    "id": "REQ-01",
                    "description": "增加未完成任务筛选",
                    "acceptance_criteria": ["筛选结果准确且现有任务不丢失"],
                    "source_ids": ["filter", "compatibility", "check"],
                }
            ],
            "constraints": ["保留现有任务数据"],
        }
    )

    refined = await AIIntentCompiler("test-model", client=fake_client).refine_plan(
        original,
        edited_canvas,
        project_context="Project: todo-demo",
    )

    assert refined.requirements[0].description == "增加未完成任务筛选"
    request_content = fake_client.responses.requests[0]["input"][0]["content"]
    assert "支持查看全部、未完成和已完成任务" in request_content
    assert "只做未完成筛选" in request_content


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
