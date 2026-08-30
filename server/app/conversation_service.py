from __future__ import annotations

import os
from pathlib import Path

from openai import AsyncOpenAI

from app.intent.models import IntentCanvas
from app.sessions import ConversationMessage
from app.workspaces import DEFAULT_IGNORED_NAMES

PROJECT_CONTEXT_MAX_FILES = 100
PROJECT_CONTEXT_MAX_CHARACTERS = 100_000
PROJECT_CONTEXT_MAX_FILE_CHARACTERS = 30_000
PROJECT_CONTEXT_IGNORED_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}


class ConversationResponseError(RuntimeError):
    """Raised when a read-only conversation response cannot be generated."""


class ConversationResponder:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 45.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        self.model = model
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )

    async def answer(
        self,
        messages: list[ConversationMessage],
        canvas: IntentCanvas | None,
        project_context: str,
        session_context: str = "",
    ) -> str:
        input_messages = build_conversation_window(messages)
        if canvas is not None:
            input_messages[-1]["content"] += (
                "\n\nThe user attached this Intent Canvas snapshot:\n"
                + canvas.model_dump_json(indent=2)
            )
        input_messages[-1]["content"] += (
            "\n\nRead-only snapshot of the current project:\n" + project_context
        )
        if session_context:
            input_messages[-1]["content"] += "\n\n" + session_context
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=ASK_INSTRUCTIONS,
                input=input_messages,
            )
        except Exception as error:
            raise ConversationResponseError(f"模型服务调用失败：{error}") from error

        output_text = str(getattr(response, "output_text", "")).strip()
        if not output_text:
            raise ConversationResponseError("模型没有返回可显示的回复")
        return output_text


def build_conversation_window(
    messages: list[ConversationMessage],
    *,
    max_messages: int = 12,
    max_characters: int = 12_000,
) -> list[dict[str, str]]:
    recent = messages[-max_messages:]
    result: list[dict[str, str]] = []
    if len(messages) > len(recent):
        earlier = messages[: -len(recent)] if recent else messages
        summary_lines = [
            f"- {message.role}/{message.mode}: {' '.join(message.content.split())[:240]}"
            for message in earlier
        ]
        summary = "[Earlier conversation compacted]\n" + "\n".join(summary_lines)
        result.append({"role": "user", "content": summary[-max_characters // 3 :]})
    result.extend({"role": message.role, "content": message.content} for message in recent)

    total = sum(len(item["content"]) for item in result)
    while len(result) > 1 and total > max_characters:
        removed = result.pop(0)
        total -= len(removed["content"])
    if result and len(result[0]["content"]) > max_characters:
        result[0]["content"] = result[0]["content"][-max_characters:]
    return result


def build_conversation_history_text(
    messages: list[ConversationMessage],
    *,
    max_characters: int = 12_000,
) -> str:
    view = build_conversation_window(
        messages,
        max_messages=12,
        max_characters=max_characters,
    )
    return "\n".join(f"{item['role']}: {item['content']}" for item in view)


def build_project_context(
    project_root: Path,
    ignored_names: frozenset[str] = DEFAULT_IGNORED_NAMES,
) -> str:
    resolved_root = project_root.resolve()
    if not resolved_root.is_dir():
        return "The configured project directory is unavailable."

    relative_files: list[str] = []
    ignored_casefold = {name.casefold() for name in ignored_names}
    for current_root, directories, filenames in os.walk(resolved_root):
        current_path = Path(current_root)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory.casefold() not in ignored_casefold
            and not (current_path / directory).is_symlink()
        )
        for filename in sorted(filenames):
            target = current_path / filename
            if filename in PROJECT_CONTEXT_IGNORED_FILES or target.is_symlink():
                continue
            relative_files.append(target.relative_to(resolved_root).as_posix())
            if len(relative_files) >= PROJECT_CONTEXT_MAX_FILES:
                break
        if len(relative_files) >= PROJECT_CONTEXT_MAX_FILES:
            break

    sections = [
        f"Project: {resolved_root.name}",
        "Files:\n" + "\n".join(f"- {path}" for path in relative_files),
        "Contents:",
    ]
    remaining = PROJECT_CONTEXT_MAX_CHARACTERS - sum(len(section) for section in sections)
    for relative_path in relative_files:
        if remaining <= 0:
            break
        target = resolved_root / Path(relative_path)
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "\x00" in content:
            continue
        if len(content) > PROJECT_CONTEXT_MAX_FILE_CHARACTERS:
            content = content[:PROJECT_CONTEXT_MAX_FILE_CHARACTERS] + "\n... file truncated"
        section = f"\n--- {relative_path} ---\n{content}"
        if len(section) > remaining:
            sections.append(section[:remaining] + "\n... project context truncated")
            remaining = 0
            break
        sections.append(section)
        remaining -= len(section)
    return "\n".join(sections)


ASK_INSTRUCTIONS = """You are the read-only conversation assistant inside IntentFlow.
Answer the user's question or help clarify their coding request in concise Chinese when they write
in Chinese. You may inspect and discuss the supplied read-only project snapshot, conversation, and
optional Canvas snapshot. You cannot change files or run commands, and must not claim that you did.
Treat structured Session and Run fields as authoritative facts. In particular, do not infer
approval or final review outcomes from conversational wording when a persisted status is present.
Do not emit hidden chain-of-thought.
"""
