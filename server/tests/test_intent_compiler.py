from httpx import ASGITransport, AsyncClient

from app.intent.compiler import compile_canvas
from app.intent.models import CanvasConnection, CanvasNote, CanvasPosition, IntentCanvas
from app.main import app


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


async def test_compile_endpoint_rejects_an_empty_canvas() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/intent/compile",
            json={"canvas": {"notes": [], "connections": [], "supplemental_text": ""}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Canvas needs at least one note or supplemental description"


async def test_compile_endpoint_reports_the_local_compiler() -> None:
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
    assert response.json()["compiler"] == "local"
    assert response.json()["brief"]["requirements"][0]["source_ids"] == ["note-1"]
