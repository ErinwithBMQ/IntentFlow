import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.models import RunReport, ToolCall, ToolResult


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
        return ToolExecution(
            result=ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=False,
                summary="Tool arguments failed validation",
                output=str(error),
            )
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


class ApplyPatchArguments(BaseModel):
    path: str
    old_text: str = Field(min_length=1)
    new_text: str


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = "Replace one exact text occurrence in a UTF-8 workspace file."
    arguments_model = ApplyPatchArguments

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
            occurrence_count = content.count(arguments.old_text)
            if occurrence_count != 1:
                raise ValueError(
                    f"old_text must match exactly once; found {occurrence_count} occurrences"
                )
            updated = content.replace(arguments.old_text, arguments.new_text, 1)
            target.write_text(updated, encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            return _failed_execution(call, str(error))

        return _successful_execution(call, f"Updated {arguments.path}", arguments.path)


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
            return _failed_execution(call, str(error))

        text = output.decode("utf-8", errors="replace")[-20_000:]
        if stopped:
            return _failed_execution(call, f"{arguments.command} command stopped by user", text)
        if timed_out:
            return _failed_execution(call, f"{arguments.command} command timed out", text)
        if process.returncode != 0:
            return _failed_execution(
                call,
                f"{arguments.command} exited with code {process.returncode}",
                text,
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

        report = RunReport.model_validate(arguments.model_dump())
        return ToolExecution(
            result=ToolResult(
                call_id=call.id,
                tool_name=call.name,
                ok=True,
                summary=f"Reported run as {arguments.status}",
                output=report.model_dump_json(),
            ),
            report=report,
        )


class ToolRegistry:
    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        registered_tools = tools or [
            ListFilesTool(),
            ReadFileTool(),
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
            return _failed_execution(call, f"Unknown tool: {call.name}")
        return await tool.execute(call, context)


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


def _failed_execution(call: ToolCall, summary: str, output: str = "") -> ToolExecution:
    return ToolExecution(
        result=ToolResult(
            call_id=call.id,
            tool_name=call.name,
            ok=False,
            summary=summary,
            output=output,
        )
    )
