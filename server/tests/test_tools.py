from app.agent.models import ToolCall
from app.agent.tools import ToolContext, ToolRegistry


async def test_apply_patch_requires_one_exact_match(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("same\nsame\n", encoding="utf-8")
    registry = ToolRegistry()
    call = ToolCall(
        id="patch-1",
        name="apply_patch",
        arguments={"path": "source.txt", "old_text": "same", "new_text": "changed"},
    )

    execution = await registry.execute(call, ToolContext(tmp_path, {}))

    assert execution.result.ok is False
    assert "found 2 occurrences" in execution.result.summary
    assert source.read_text(encoding="utf-8") == "same\nsame\n"


async def test_completed_report_requires_evidence(tmp_path) -> None:
    registry = ToolRegistry()
    call = ToolCall(
        id="report-1",
        name="report_result",
        arguments={
            "status": "completed",
            "summary": "Done",
            "evidence": [],
            "requirements": [
                {
                    "requirement_id": "REQ-1",
                    "status": "verified",
                    "summary": "Claimed result",
                }
            ],
        },
    )

    execution = await registry.execute(call, ToolContext(tmp_path, {}))

    assert execution.result.ok is False
    assert execution.report is None
    assert "requires at least one evidence" in execution.result.summary
