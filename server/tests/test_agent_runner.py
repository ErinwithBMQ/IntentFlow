import asyncio
import sys

from app.agent.model_client import FakeModelClient
from app.agent.models import IntentBrief, IntentRequirement, ModelTurn, ToolCall
from app.agent.runner import AgentRunner
from app.agent.tools import ToolContext, ToolRegistry


def make_intent() -> IntentBrief:
    return IntentBrief(
        title="Update demo behavior",
        goal="Change the value and prove it with an automated check.",
        requirements=[
            IntentRequirement(
                id="REQ-1",
                description="The exported value is 2.",
                acceptance_criteria=["The verification command exits with code 0."],
                source_ids=["card-1"],
            )
        ],
    )


async def test_fake_model_completes_a_tool_loop(tmp_path) -> None:
    source = tmp_path / "value.js"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    turns = [
        ModelTurn(
            action="Inspect the current implementation",
            reason="Locate the exact value before editing.",
            related_requirement_ids=["REQ-1"],
            tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "value.js"})],
        ),
        ModelTurn(
            action="Apply the requested change",
            reason="The old value is present exactly once.",
            related_requirement_ids=["REQ-1"],
            tool_calls=[
                ToolCall(
                    id="call-2",
                    name="apply_patch",
                    arguments={
                        "path": "value.js",
                        "old_text": "export const value = 1;",
                        "new_text": "export const value = 2;",
                    },
                )
            ],
        ),
        ModelTurn(
            action="Verify the changed behavior",
            reason="A passing command is required as completion evidence.",
            related_requirement_ids=["REQ-1"],
            tool_calls=[ToolCall(id="call-3", name="run_command", arguments={"command": "test"})],
        ),
        ModelTurn(
            action="Report the verified result",
            reason="The file changed and the verification command passed.",
            related_requirement_ids=["REQ-1"],
            tool_calls=[
                ToolCall(
                    id="call-4",
                    name="report_result",
                    arguments={
                        "status": "completed",
                        "summary": "Updated and verified the requested behavior.",
                        "evidence": ["test command exited with code 0"],
                        "requirements": [
                            {
                                "requirement_id": "REQ-1",
                                "status": "verified",
                                "summary": "The requested value was updated and tested.",
                            }
                        ],
                    },
                )
            ],
        ),
    ]
    model = FakeModelClient(turns)
    context = ToolContext(
        tmp_path,
        allowed_commands={
            "test": (
                sys.executable,
                "-c",
                "from pathlib import Path; assert 'value = 2' in Path('value.js').read_text()",
            )
        },
    )
    runner = AgentRunner(model, ToolRegistry(), context)

    result = await runner.run(make_intent())

    assert result.status == "completed"
    assert result.steps == 4
    assert source.read_text(encoding="utf-8") == "export const value = 2;\n"
    assert [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
    assert any(event.tool_name == "run_command" for event in result.events)
    assert len(model.received_histories[-1]) == 6
    assert result.report.evidence == ["test exited with code 0"]
    requirement = result.report.requirement_results[0]
    assert requirement.requirement_id == "REQ-1"
    assert requirement.status == "verified"
    assert requirement.related_files == ["value.js"]
    assert requirement.evidence == ["test exited with code 0"]


async def test_tool_failure_is_returned_to_the_model(tmp_path) -> None:
    model = FakeModelClient(
        [
            ModelTurn(
                action="Try the requested file",
                reason="Inspect the supplied path.",
                tool_calls=[
                    ToolCall(id="call-1", name="read_file", arguments={"path": "../secret.txt"})
                ],
            ),
            ModelTurn(
                action="Report the blocked operation",
                reason="The file is outside the controlled workspace.",
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="report_result",
                        arguments={
                            "status": "failed",
                            "summary": "The requested path was rejected.",
                            "unresolved": ["Path escapes the workspace"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "failed",
                                    "summary": "The requested path was rejected.",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )
    runner = AgentRunner(model, ToolRegistry(), ToolContext(tmp_path, {}))

    result = await runner.run(make_intent())

    first_tool_result = model.received_histories[1][-1]
    assert first_tool_result.ok is False
    assert "escapes the workspace" in first_tool_result.summary
    assert result.status == "failed"


async def test_stop_signal_ends_before_model_call(tmp_path) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    model = FakeModelClient([])
    runner = AgentRunner(
        model,
        ToolRegistry(),
        ToolContext(tmp_path, {}, stop_event=stop_event),
    )

    result = await runner.run(make_intent())

    assert result.status == "stopped"
    assert result.steps == 0
    assert model.received_histories == []


async def test_stop_signal_cancels_an_in_progress_model_call(tmp_path) -> None:
    class SlowModel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = False

        async def next_turn(self, intent, history):
            del intent, history
            self.started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    stop_event = asyncio.Event()
    model = SlowModel()
    runner = AgentRunner(model, ToolRegistry(), ToolContext(tmp_path, {}, stop_event=stop_event))

    run_task = asyncio.create_task(runner.run(make_intent()))
    await model.started.wait()
    stop_event.set()
    result = await asyncio.wait_for(run_task, timeout=1)

    assert result.status == "stopped"
    assert model.cancelled is True


async def test_step_limit_fails_an_unfinished_run(tmp_path) -> None:
    model = FakeModelClient(
        [ModelTurn(action="Still planning", reason="No terminal tool call yet.")]
    )
    runner = AgentRunner(model, ToolRegistry(), ToolContext(tmp_path, {}), max_steps=1)

    result = await runner.run(make_intent())

    assert result.status == "failed"
    assert "step limit" in result.report.summary


async def test_model_cannot_claim_completion_without_real_verification(tmp_path) -> None:
    model = FakeModelClient(
        [
            ModelTurn(
                action="Claim completion",
                reason="Pretend the work passed.",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "Done",
                            "evidence": ["tests passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "Claimed without running a command.",
                                }
                            ],
                        },
                    )
                ],
            )
        ]
    )
    runner = AgentRunner(
        model,
        ToolRegistry(),
        ToolContext(tmp_path, {}),
        max_steps=1,
    )

    result = await runner.run(make_intent())

    assert result.status == "failed"
    tool_event = next(event for event in result.events if event.kind == "tool_finished")
    assert tool_event.status == "failed"
    assert "test or build command" in tool_event.action


async def test_edit_invalidates_earlier_verification(tmp_path) -> None:
    source = tmp_path / "value.js"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    model = FakeModelClient(
        [
            ModelTurn(
                action="Run an early test",
                reason="Establish the initial state.",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(id="call-1", name="run_command", arguments={"command": "test"})
                ],
            ),
            ModelTurn(
                action="Edit after testing",
                reason="This makes the earlier evidence stale.",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="apply_patch",
                        arguments={
                            "path": "value.js",
                            "old_text": "value = 1",
                            "new_text": "value = 2",
                        },
                    )
                ],
            ),
            ModelTurn(
                action="Claim completion",
                reason="Try to reuse stale evidence.",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="call-3",
                        name="report_result",
                        arguments={
                            "status": "completed",
                            "summary": "Done",
                            "evidence": ["the earlier test passed"],
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "Try to reuse stale evidence.",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )
    runner = AgentRunner(
        model,
        ToolRegistry(),
        ToolContext(
            tmp_path,
            {"test": (sys.executable, "-c", "raise SystemExit(0)")},
        ),
        max_steps=3,
    )

    result = await runner.run(make_intent())

    assert result.status == "failed"
    assert result.report.summary.endswith("step limit")
    requirement = result.report.requirement_results[0]
    assert requirement.status == "implemented"
    assert requirement.related_files == ["value.js"]
    assert requirement.evidence == []


async def test_runner_downgrades_unverified_requirement_claim_to_implemented(tmp_path) -> None:
    source = tmp_path / "value.js"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    model = FakeModelClient(
        [
            ModelTurn(
                action="Edit the requested value",
                reason="Implement the requirement.",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="apply_patch",
                        arguments={
                            "path": "value.js",
                            "old_text": "value = 1",
                            "new_text": "value = 2",
                        },
                    )
                ],
            ),
            ModelTurn(
                action="Report without verification",
                reason="No command was run.",
                related_requirement_ids=["REQ-1"],
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="report_result",
                        arguments={
                            "status": "partial",
                            "summary": "Implemented but not tested.",
                            "requirements": [
                                {
                                    "requirement_id": "REQ-1",
                                    "status": "verified",
                                    "summary": "The model claims this is verified.",
                                }
                            ],
                        },
                    )
                ],
            ),
        ]
    )

    result = await AgentRunner(model, ToolRegistry(), ToolContext(tmp_path, {})).run(make_intent())

    requirement = result.report.requirement_results[0]
    assert result.status == "partial"
    assert requirement.status == "implemented"
    assert requirement.summary == "已修改关联文件，但缺少需求级验证证据"
    assert requirement.related_files == ["value.js"]
    assert requirement.evidence == []


async def test_runner_rejects_incomplete_requirement_claims(tmp_path) -> None:
    model = FakeModelClient(
        [
            ModelTurn(
                action="Report an unknown requirement",
                reason="Exercise claim validation.",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="report_result",
                        arguments={
                            "status": "failed",
                            "summary": "Invalid claims",
                            "requirements": [
                                {
                                    "requirement_id": "REQ-UNKNOWN",
                                    "status": "failed",
                                    "summary": "Wrong requirement ID",
                                }
                            ],
                        },
                    )
                ],
            )
        ]
    )
    runner = AgentRunner(model, ToolRegistry(), ToolContext(tmp_path, {}), max_steps=1)

    result = await runner.run(make_intent())

    tool_event = next(event for event in result.events if event.kind == "tool_finished")
    assert result.status == "failed"
    assert tool_event.action == "Requirement claims failed validation"
