import asyncio
import difflib
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.models import RequirementClaim, RunReport, ToolCall, ToolError, ToolResult


class ToolContext:
    def __init__(
        self,
        workspace_root: Path,
        allowed_commands: dict[str, tuple[str, ...]],
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.allowed_commands = allowed_commands
        self.stop_event = stop_event or asyncio.Event()

    def resolve_path(self, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            raise ValueError("Only relative workspace paths are allowed")

        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError as error:
            raise ValueError("Path escapes the workspace") from error
        return target


class ToolExecution(BaseModel):
    result: ToolResult
    report: RunReport | None = None
    requirement_claims: list[RequirementClaim] = Field(default_factory=list)


class ToolApprovalPreview(BaseModel):
    target: str
    patch: str


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    arguments_model: ClassVar[type[BaseModel]]

    def schema(self) -> dict[str, Any]:
        parameters = self.arguments_model.model_json_schema()
        parameters["properties"]["_intentflow"] = {
            "type": "object",
            "description": "Visible context explaining this action to the user.",
            "properties": {
                "action": {"type": "string"},
                "reason": {"type": "string"},
                "related_requirement_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["action", "reason", "related_requirement_ids"],
            "additionalProperties": False,
        }
        parameters.setdefault("required", []).append("_intentflow")
        parameters["additionalProperties"] = False
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
            "strict": False,
        }

    def invalid_arguments(self, call: ToolCall, error: ValidationError) -> ToolExecution:
        return _failed_execution(
            call,
            "Tool arguments failed validation",
            str(error),
            kind="invalid_arguments",
            retryable=True,
            suggestion="Correct the tool arguments and call the tool again.",
        )

    @abstractmethod
    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        raise NotImplementedError


class ListFilesArguments(BaseModel):
    path: str = "."


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files below a relative workspace directory."
    arguments_model = ListFilesArguments
    ignored_names = {".git", "node_modules", "dist", "coverage", "__pycache__"}

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        try:
            target = context.resolve_path(arguments.path)
            if not target.is_dir():
                raise ValueError("Directory does not exist")

            files: list[str] = []
            for current_root, directories, filenames in os.walk(target):
                directories[:] = sorted(
                    directory for directory in directories if directory not in self.ignored_names
                )
                for filename in sorted(filenames):
                    file_path = Path(current_root) / filename
                    files.append(file_path.relative_to(context.workspace_root).as_posix())
                    if len(files) == 200:
                        files.append("... file list truncated at 200 entries")
                        break
                if len(files) > 200:
                    break
        except (OSError, ValueError) as error:
            return _failed_execution(call, str(error))

        return _successful_execution(call, f"Listed {len(files)} entries", "\n".join(files))


class ReadFileArguments(BaseModel):
    path: str


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read one UTF-8 text file from the workspace."
    arguments_model = ReadFileArguments
    max_characters = 40_000

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        try:
            target = context.resolve_path(arguments.path)
            if not target.is_file():
                raise ValueError("File does not exist")
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            return _failed_execution(call, str(error))

        truncated = len(content) > self.max_characters
        output = content[: self.max_characters]
        if truncated:
            output += "\n... file content truncated"
        return _successful_execution(call, f"Read {arguments.path}", output)


class SearchCodeArguments(BaseModel):
    query: str = Field(min_length=1)
    path: str = "."
    regex: bool = False
    case_sensitive: bool = False
    max_results: int = Field(default=100, ge=1, le=500)


class SearchCodeTool(BaseTool):
    name = "search_code"
    description = (
        "Search UTF-8 text files inside the workspace using plain text or a regular expression."
    )
    arguments_model = SearchCodeArguments
    ignored_names = ListFilesTool.ignored_names

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        flags = 0 if arguments.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(
                arguments.query if arguments.regex else re.escape(arguments.query),
                flags,
            )
        except re.error as error:
            return _failed_execution(
                call,
                "Search pattern is invalid",
                str(error),
                kind="invalid_arguments",
                retryable=True,
                suggestion="Correct the regular expression and search again.",
            )

        try:
            target = context.resolve_path(arguments.path)
            if not target.exists():
                return _failed_execution(
                    call,
                    "Search path does not exist",
                    kind="not_found",
                    retryable=True,
                    suggestion="List workspace files and choose an existing relative path.",
                    details={"path": arguments.path},
                )
            files = [target] if target.is_file() else self._files(target)
            matches: list[str] = []
            scanned_files = 0
            for file_path in files:
                if file_path.is_symlink():
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                if "\x00" in content:
                    continue
                scanned_files += 1
                relative = file_path.relative_to(context.workspace_root).as_posix()
                for line_number, line in enumerate(content.splitlines(), start=1):
                    if pattern.search(line) is None:
                        continue
                    rendered = line if len(line) <= 500 else line[:500] + "... [truncated]"
                    matches.append(f"{relative}:{line_number}:{rendered}")
                    if len(matches) >= arguments.max_results:
                        break
                if len(matches) >= arguments.max_results:
                    break
        except (OSError, ValueError) as error:
            return _failed_execution(
                call,
                "Search could not access the requested path",
                str(error),
                kind="path_error",
                retryable=True,
                suggestion="Use a relative path inside the workspace.",
            )

        suffix = " (result limit reached)" if len(matches) >= arguments.max_results else ""
        return _successful_execution(
            call,
            f"Found {len(matches)} matches in {scanned_files} files{suffix}",
            "\n".join(matches) or "No matches found",
        )

    def _files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for current_root, directories, filenames in os.walk(root):
            directories[:] = sorted(
                name
                for name in directories
                if name not in self.ignored_names and not (Path(current_root) / name).is_symlink()
            )
            files.extend(Path(current_root) / name for name in sorted(filenames))
        return files


class PatchEdit(BaseModel):
    old_text: str = Field(min_length=1)
    new_text: str


class ApplyPatchArguments(BaseModel):
    path: str
    operation: Literal["update", "create", "delete"] = "update"
    old_text: str | None = None
    new_text: str | None = None
    edits: list[PatchEdit] = Field(default_factory=list)


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = (
        "Create, delete, or update one UTF-8 workspace file. Updates may contain multiple "
        "ordered exact-text edits."
    )
    arguments_model = ApplyPatchArguments

    def preview(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolApprovalPreview | ToolExecution:
        prepared = self._prepare(call, context)
        if isinstance(prepared, ToolExecution):
            return prepared
        arguments, _, content, updated = prepared
        fromfile = "/dev/null" if arguments.operation == "create" else f"a/{arguments.path}"
        tofile = "/dev/null" if arguments.operation == "delete" else f"b/{arguments.path}"
        patch = "".join(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=fromfile,
                tofile=tofile,
            )
        )
        return ToolApprovalPreview(target=arguments.path, patch=patch)

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        prepared = self._prepare(call, context)
        if isinstance(prepared, ToolExecution):
            return prepared
        arguments, target, _, updated = prepared
        try:
            if arguments.operation == "delete":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(updated, encoding="utf-8")
        except OSError as error:
            return _failed_execution(
                call,
                f"Could not {arguments.operation} {arguments.path}",
                str(error),
                kind="io_error",
                retryable=True,
                suggestion="Inspect the target path and retry with a valid patch.",
            )
        action = {"create": "Created", "delete": "Deleted", "update": "Updated"}[
            arguments.operation
        ]
        return _successful_execution(call, f"{action} {arguments.path}", arguments.path)

    def _prepare(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> tuple[ApplyPatchArguments, Path, str, str] | ToolExecution:
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        try:
            target = context.resolve_path(arguments.path)
            if arguments.operation == "create":
                if target.exists():
                    return _failed_execution(
                        call,
                        "Target file already exists",
                        kind="conflict",
                        retryable=True,
                        suggestion="Read the existing file and use operation='update'.",
                        details={"path": arguments.path},
                    )
                if arguments.new_text is None:
                    return _failed_execution(
                        call,
                        "Create operation requires new_text",
                        kind="invalid_arguments",
                        retryable=True,
                        suggestion="Provide the complete new file content in new_text.",
                    )
                return arguments, target, "", arguments.new_text

            if not target.is_file():
                return _failed_execution(
                    call,
                    "File does not exist",
                    kind="not_found",
                    retryable=True,
                    suggestion="List or search files and retry with an existing relative path.",
                    details={"path": arguments.path},
                )
            content = target.read_text(encoding="utf-8")
            if arguments.operation == "delete":
                return arguments, target, content, ""

            edits = list(arguments.edits)
            if arguments.old_text is not None:
                edits.insert(
                    0,
                    PatchEdit(
                        old_text=arguments.old_text,
                        new_text=arguments.new_text or "",
                    ),
                )
            if not edits:
                return _failed_execution(
                    call,
                    "Update operation requires old_text/new_text or edits",
                    kind="invalid_arguments",
                    retryable=True,
                    suggestion="Provide one or more exact-text edits.",
                )

            updated = content
            for index, edit in enumerate(edits):
                occurrence_count = updated.count(edit.old_text)
                if occurrence_count != 1:
                    return _failed_execution(
                        call,
                        f"old_text must match exactly once; found {occurrence_count} occurrences",
                        kind="conflict",
                        retryable=True,
                        suggestion="Read the latest file content and submit a more specific edit.",
                        details={
                            "path": arguments.path,
                            "edit_index": index,
                            "expected_matches": 1,
                            "actual_matches": occurrence_count,
                        },
                    )
                updated = updated.replace(edit.old_text, edit.new_text, 1)
        except (OSError, UnicodeError, ValueError) as error:
            return _failed_execution(
                call,
                "Patch preparation failed",
                str(error),
                kind="io_error",
                retryable=True,
                suggestion="Read the latest file content and retry.",
            )
        return arguments, target, content, updated


class RunCommandArguments(BaseModel):
    command: Literal["test", "build"]


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Run one pre-approved project command by its test or build identifier."
    arguments_model = RunCommandArguments
    timeout_seconds = 60

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        command = context.allowed_commands.get(arguments.command)
        if command is None:
            return _failed_execution(call, f"Command is not configured: {arguments.command}")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=context.workspace_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, stopped, timed_out = await self._wait_for_process(process, context.stop_event)
        except OSError as error:
            return _failed_execution(
                call,
                "Command could not be started",
                str(error),
                kind="io_error",
                retryable=False,
            )

        text = _summarize_command_output(output.decode("utf-8", errors="replace"))
        if stopped:
            return _failed_execution(
                call,
                f"{arguments.command} command stopped by user",
                text,
                kind="cancelled",
                retryable=False,
            )
        if timed_out:
            return _failed_execution(
                call,
                f"{arguments.command} command timed out",
                text,
                kind="timeout",
                retryable=True,
                suggestion="Inspect the partial output, narrow the command, or retry once.",
            )
        if process.returncode != 0:
            return _failed_execution(
                call,
                f"{arguments.command} exited with code {process.returncode}",
                text,
                kind="verification_failed",
                retryable=True,
                suggestion=(
                    "Use the failing cases and file locations to fix the code, "
                    "then rerun verification."
                ),
                details={"exit_code": process.returncode},
            )
        return _successful_execution(
            call,
            f"{arguments.command} exited with code {process.returncode}",
            text,
        )

    async def _wait_for_process(
        self,
        process: asyncio.subprocess.Process,
        stop_event: asyncio.Event,
    ) -> tuple[bytes, bool, bool]:
        communicate_task = asyncio.create_task(process.communicate())
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {communicate_task, stop_task},
            timeout=self.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )

        stopped = stop_task in done and stop_event.is_set()
        timed_out = not done
        if stopped or timed_out:
            process.kill()
            await process.wait()

        if communicate_task.done():
            output, _ = communicate_task.result()
        else:
            communicate_task.cancel()
            await asyncio.gather(communicate_task, return_exceptions=True)
            output = b""

        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        return output, stopped, timed_out


class ReportResultArguments(BaseModel):
    status: Literal["completed", "partial", "failed"]
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    requirements: list[RequirementClaim]


class ReportResultTool(BaseTool):
    name = "report_result"
    description = "Finish the run with a status, evidence, and unresolved items."
    arguments_model = ReportResultArguments

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        del context
        try:
            arguments = self.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            return self.invalid_arguments(call, error)

        if arguments.status == "completed" and not arguments.evidence:
            return _failed_execution(call, "A completed report requires at least one evidence item")

        report = RunReport(
            status=arguments.status,
            summary=arguments.summary,
            evidence=arguments.evidence,
            unresolved=arguments.unresolved,
        )
        return ToolExecution(
            result=ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=True,
                summary=f"Reported run as {arguments.status}",
                output=report.model_dump_json(),
            ),
            report=report,
            requirement_claims=arguments.requirements,
        )


class ToolRegistry:
    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        registered_tools = tools or [
            ListFilesTool(),
            ReadFileTool(),
            SearchCodeTool(),
            ApplyPatchTool(),
            RunCommandTool(),
            ReportResultTool(),
        ]
        self._tools = {tool.name: tool for tool in registered_tools}

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolExecution:
        tool = self._tools.get(call.name)
        if tool is None:
            return _failed_execution(
                call,
                f"Unknown tool: {call.name}",
                kind="unknown_tool",
                retryable=True,
                suggestion="Choose one of the provided tool schemas.",
            )
        return await tool.execute(call, context)

    def approval_preview(
        self,
        call: ToolCall,
        context: ToolContext,
    ) -> ToolApprovalPreview | ToolExecution | None:
        tool = self._tools.get(call.name)
        if isinstance(tool, ApplyPatchTool):
            return tool.preview(call, context)
        return None


def _successful_execution(call: ToolCall, summary: str, output: str) -> ToolExecution:
    return ToolExecution(
        result=ToolResult(
            call_id=call.id,
            tool_name=call.name,
            ok=True,
            summary=summary,
            output=output,
        )
    )


def _failed_execution(
    call: ToolCall,
    summary: str,
    output: str = "",
    *,
    kind: Literal[
        "invalid_arguments",
        "path_error",
        "not_found",
        "conflict",
        "io_error",
        "verification_failed",
        "timeout",
        "cancelled",
        "user_rejected",
        "unknown_tool",
    ] = "io_error",
    retryable: bool = False,
    suggestion: str = "",
    details: dict[str, Any] | None = None,
) -> ToolExecution:
    return ToolExecution(
        result=ToolResult(
            call_id=call.id,
            tool_name=call.name,
            ok=False,
            summary=summary,
            output=output,
            error=ToolError(
                kind=kind,
                message=summary,
                retryable=retryable,
                suggestion=suggestion,
                details=details or {},
            ),
        )
    )


def _summarize_command_output(output: str, max_characters: int = 12_000) -> str:
    if len(output) <= max_characters:
        return output

    lines = output.splitlines()
    important_pattern = re.compile(
        r"fail|error|exception|assert|expected|received|traceback|\.(?:js|ts|tsx|py):\d+",
        re.IGNORECASE,
    )
    important = [
        _clip_log_line(line)
        for line in lines
        if important_pattern.search(line)
    ][:120]
    important_text = "\n".join(_unique_strings(important))
    if len(important_text) >= max_characters:
        rendered = important_text[:max_characters]
    else:
        important_values = set(important)
        tail: list[str] = []
        for line in lines[-120:]:
            clipped = _clip_log_line(line)
            if clipped not in important_values:
                tail.append(clipped)
        tail_text = "\n".join(_unique_strings(tail))
        remaining = max_characters - len(important_text) - (1 if important_text else 0)
        tail_suffix = tail_text[-remaining:] if remaining > 0 else ""
        rendered = "\n".join(
            value for value in [important_text, tail_suffix] if value
        )
    omitted = max(0, len(output) - len(rendered))
    return f"... {omitted} characters omitted; key failures and tail retained ...\n{rendered}"


def _clip_log_line(line: str, max_characters: int = 1_000) -> str:
    if len(line) <= max_characters:
        return line
    half = max_characters // 2
    return line[:half] + " ... [line truncated] ... " + line[-half:]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
