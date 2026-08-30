from app.agent.context import ContextBudget, ContextManager
from app.agent.models import (
    ContextCheckpoint,
    ContextSummary,
    IntentBrief,
    IntentRequirement,
    ModelTurn,
    ModelUsage,
    ToolCall,
    ToolResult,
)


def make_intent() -> IntentBrief:
    return IntentBrief(
        title="Search tasks",
        goal="Add searchable tasks",
        constraints=["Do not add dependencies"],
        requirements=[IntentRequirement(id="REQ-1", description="Search existing tasks")],
    )


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def summarize_context(
        self,
        transcript: str,
        previous_summary: str,
    ) -> tuple[str, ModelUsage]:
        self.calls.append((transcript, previous_summary))
        return "Earlier work was summarized safely.", ModelUsage(
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
        )


async def test_context_manager_compacts_without_mutating_history() -> None:
    summarizer = FakeSummarizer()
    manager = ContextManager(
        make_intent(),
        budget=ContextBudget(
            context_window_tokens=500,
            reserve_output_tokens=100,
            keep_recent_tokens=60,
            compact_at_ratio=0.8,
            max_tool_output_characters=400,
        ),
        summarizer=summarizer,
    )
    history = []
    for index in range(8):
        history.extend(
            [
                ModelTurn(
                    action=f"Inspect {index}",
                    reason="x" * 120,
                    tool_calls=[ToolCall(id=f"call-{index}", name="read_file")],
                ),
                ToolResult(
                    call_id=f"call-{index}",
                    tool_name="read_file",
                    ok=True,
                    summary=f"Read file {index}",
                    output="content " * 120,
                ),
            ]
        )
    original_output = history[1].output

    prepared = await manager.prepare(make_intent(), history, step=1)

    assert summarizer.calls
    assert manager.checkpoint.compression_count == 1
    assert manager.checkpoint.covered_history_items > 0
    assert history[1].output == original_output
    assert isinstance(prepared.history[0], ContextSummary)
    assert "Earlier work was summarized safely" in prepared.history[0].content
    assert "older_model_turns" in prepared.discarded_content_types


async def test_context_manager_restores_checkpoint_and_keeps_structured_facts() -> None:
    checkpoint = ContextCheckpoint(
        summary="Previous summary",
        covered_history_items=2,
        modified_files=["src/tasks.js"],
        verification_results=["test exited with code 0"],
        approval_decisions=["src/tasks.js: approved"],
    )
    manager = ContextManager(
        make_intent(),
        checkpoint=checkpoint,
        prior_context="Earlier run applied",
    )
    history = [
        ModelTurn(action="old", reason="old"),
        ToolResult(call_id="old", tool_name="read_file", ok=True, summary="old"),
        ModelTurn(action="current", reason="continue"),
    ]

    prepared = await manager.prepare(make_intent(), history, step=2)
    content = prepared.history[0].content

    assert len(prepared.history) == 2
    assert "Previous summary" in content
    assert "Earlier run applied" in content
    assert "src/tasks.js" in content
    assert "test exited with code 0" in content
    assert "approved" in content


def test_context_manager_invalidates_verification_after_patch() -> None:
    manager = ContextManager(make_intent())
    manager.record_tool(
        ToolCall(id="test", name="run_command", arguments={"command": "test"}),
        ToolResult(call_id="test", tool_name="run_command", ok=True, summary="test passed"),
    )
    assert manager.checkpoint.verification_results == ["test passed"]

    manager.record_tool(
        ToolCall(id="patch", name="apply_patch", arguments={"path": "src/tasks.js"}),
        ToolResult(call_id="patch", tool_name="apply_patch", ok=True, summary="updated"),
    )

    assert manager.checkpoint.verification_results == []
    assert manager.checkpoint.modified_files == ["src/tasks.js"]
