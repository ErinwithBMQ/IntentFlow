import sys

import pytest

from app.agent.models import ToolCall
from app.agent.tools import (
    ToolContext,
    ToolRegistry,
    _resolve_windows_command_executable,
)


def test_windows_command_resolves_bare_npm_to_cmd(monkeypatch) -> None:
    npm_cmd = r"F:\NVM\nodejs\npm.cmd"
    monkeypatch.setattr(
        "app.agent.tools.shutil.which",
        lambda executable: npm_cmd if executable == "npm.cmd" else None,
    )

    resolved = _resolve_windows_command_executable(("npm", "run", "build"))

    assert resolved == (npm_cmd, "run", "build")


def test_windows_command_keeps_non_npm_executable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent.tools.shutil.which",
        lambda executable: pytest.fail(f"unexpected lookup: {executable}"),
    )

    resolved = _resolve_windows_command_executable((sys.executable, "-m", "pytest"))

    assert resolved == (sys.executable, "-m", "pytest")


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
    assert execution.result.error is not None
    assert execution.result.error.kind == "conflict"
    assert execution.result.error.retryable is True
    assert execution.result.error.details["actual_matches"] == 2
    assert source.read_text(encoding="utf-8") == "same\nsame\n"


async def test_search_code_supports_plain_text_and_regex(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "tasks.js").write_text(
        "export function addTask() {}\nexport function removeTask() {}\n",
        encoding="utf-8",
    )
    registry = ToolRegistry()

    plain = await registry.execute(
        ToolCall(
            id="search-plain",
            name="search_code",
            arguments={"query": "addtask", "path": "src"},
        ),
        ToolContext(tmp_path, {}),
    )
    regex = await registry.execute(
        ToolCall(
            id="search-regex",
            name="search_code",
            arguments={"query": "function (add|remove)Task", "path": "src", "regex": True},
        ),
        ToolContext(tmp_path, {}),
    )

    assert plain.result.ok is True
    assert "src/tasks.js:1:" in plain.result.output
    assert regex.result.ok is True
    assert "Found 2 matches" in regex.result.summary


async def test_search_code_rejects_invalid_regex(tmp_path) -> None:
    execution = await ToolRegistry().execute(
        ToolCall(
            id="search-invalid",
            name="search_code",
            arguments={"query": "[", "regex": True},
        ),
        ToolContext(tmp_path, {}),
    )

    assert execution.result.ok is False
    assert execution.result.error is not None
    assert execution.result.error.kind == "invalid_arguments"
    assert execution.result.error.retryable is True


async def test_apply_patch_supports_create_multi_edit_and_delete(tmp_path) -> None:
    registry = ToolRegistry()
    context = ToolContext(tmp_path, {})

    created = await registry.execute(
        ToolCall(
            id="create",
            name="apply_patch",
            arguments={"path": "src/new.js", "operation": "create", "new_text": "one\ntwo\n"},
        ),
        context,
    )
    updated = await registry.execute(
        ToolCall(
            id="update",
            name="apply_patch",
            arguments={
                "path": "src/new.js",
                "edits": [
                    {"old_text": "one", "new_text": "first"},
                    {"old_text": "two", "new_text": "second"},
                ],
            },
        ),
        context,
    )
    preview = registry.approval_preview(
        ToolCall(
            id="delete-preview",
            name="apply_patch",
            arguments={"path": "src/new.js", "operation": "delete"},
        ),
        context,
    )
    deleted = await registry.execute(
        ToolCall(
            id="delete",
            name="apply_patch",
            arguments={"path": "src/new.js", "operation": "delete"},
        ),
        context,
    )

    assert created.result.ok is True
    assert updated.result.ok is True
    assert "first\nsecond" in updated.result.output or updated.result.output == "src/new.js"
    assert preview.patch.startswith("--- a/src/new.js\n+++ /dev/null")
    assert deleted.result.ok is True
    assert not (tmp_path / "src" / "new.js").exists()


async def test_completed_report_allows_missing_automated_evidence(tmp_path) -> None:
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

    assert execution.result.ok is True
    assert execution.report is not None
    assert execution.report.status == "completed"
    assert execution.report.evidence == []


async def test_unconfigured_command_has_a_distinct_verification_status(tmp_path) -> None:
    execution = await ToolRegistry().execute(
        ToolCall(
            id="test-unconfigured",
            name="run_command",
            arguments={"command": "test"},
        ),
        ToolContext(tmp_path, {}),
    )

    assert execution.result.ok is False
    assert execution.result.verification_status == "not_configured"
    assert execution.result.error is not None
    assert execution.result.error.kind == "command_not_configured"
    assert execution.result.error.retryable is False
    assert "Do not retry" in execution.result.error.suggestion


async def test_command_start_failure_has_a_distinct_verification_status(tmp_path) -> None:
    missing_executable = tmp_path / "missing-command.exe"
    execution = await ToolRegistry().execute(
        ToolCall(
            id="test-start-failure",
            name="run_command",
            arguments={"command": "test"},
        ),
        ToolContext(tmp_path, {"test": (str(missing_executable),)}),
    )

    assert execution.result.ok is False
    assert execution.result.verification_status == "command_start_failed"
    assert execution.result.error is not None
    assert execution.result.error.kind == "command_start_failed"
    assert execution.result.error.retryable is False


async def test_successful_command_is_recorded_as_passed_verification(tmp_path) -> None:
    execution = await ToolRegistry().execute(
        ToolCall(
            id="test-success",
            name="run_command",
            arguments={"command": "test"},
        ),
        ToolContext(tmp_path, {"test": (sys.executable, "-c", "print('ok')")}),
    )

    assert execution.result.ok is True
    assert execution.result.verification_status == "passed"


async def test_failed_command_retains_key_failure_from_long_output(tmp_path) -> None:
    command = (
        sys.executable,
        "-c",
        (
            "print('noise' * 3000); "
            "print('AssertionError: tests/test_value.py:7 expected 2 received 1'); "
            "raise SystemExit(1)"
        ),
    )
    execution = await ToolRegistry().execute(
        ToolCall(
            id="test-long-failure",
            name="run_command",
            arguments={"command": "test"},
        ),
        ToolContext(tmp_path, {"test": command}),
    )

    assert execution.result.ok is False
    assert execution.result.verification_status == "failed"
    assert execution.result.error is not None
    assert execution.result.error.kind == "verification_failed"
    assert "AssertionError" in execution.result.output
    assert "tests/test_value.py:7" in execution.result.output
    assert "characters omitted" in execution.result.output
