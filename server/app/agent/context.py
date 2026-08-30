from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from pydantic import BaseModel

from app.agent.models import (
    AgentHistoryItem,
    ContextCheckpoint,
    ContextRoundMetrics,
    ContextSummary,
    IntentBrief,
    ModelTurn,
    ModelUsage,
    RunMetrics,
    ToolCall,
    ToolResult,
)


class ContextBudget(BaseModel):
    context_window_tokens: int = 64_000
    reserve_output_tokens: int = 8_000
    keep_recent_tokens: int = 12_000
    compact_at_ratio: float = 0.8
    max_tool_output_characters: int = 12_000
    fallback_summary_characters: int = 6_000

    def validate_limits(self) -> None:
        if self.context_window_tokens < 1:
            raise ValueError("context_window_tokens must be positive")
        if not 0 <= self.reserve_output_tokens < self.context_window_tokens:
            raise ValueError("reserve_output_tokens must be smaller than the context window")
        if self.keep_recent_tokens < 1:
            raise ValueError("keep_recent_tokens must be positive")
        if not 0 < self.compact_at_ratio <= 1:
            raise ValueError("compact_at_ratio must be between 0 and 1")
        if self.max_tool_output_characters < 200:
            raise ValueError("max_tool_output_characters must be at least 200")

    @property
    def compaction_threshold(self) -> int:
        available = self.context_window_tokens - self.reserve_output_tokens
        return max(1, int(available * self.compact_at_ratio))


class ContextSummarizer(Protocol):
    async def summarize_context(
        self,
        transcript: str,
        previous_summary: str,
    ) -> tuple[str, ModelUsage | None]: ...


@dataclass(frozen=True)
class PreparedContext:
    history: list[AgentHistoryItem]
    estimated_input_tokens: int
    compressed: bool
    discarded_content_types: list[str]


class ContextManager:
    """Owns the bounded, non-destructive history view sent to the coding model."""

    def __init__(
        self,
        intent: IntentBrief,
        *,
        budget: ContextBudget | None = None,
        summarizer: ContextSummarizer | None = None,
        checkpoint: ContextCheckpoint | None = None,
        prior_context: str = "",
    ) -> None:
        self.budget = budget or ContextBudget()
        self.budget.validate_limits()
        self.summarizer = summarizer
        self.prior_context = prior_context.strip()
        self.checkpoint = checkpoint.model_copy(deep=True) if checkpoint else ContextCheckpoint()
        self.checkpoint.current_goal = intent.goal
        self.checkpoint.constraints = list(intent.constraints)
        self.metrics = RunMetrics()
        self._started_at = monotonic()

    async def prepare(
        self,
        intent: IntentBrief,
        history: Sequence[AgentHistoryItem],
        *,
        step: int,
    ) -> PreparedContext:
        history_items = list(history)
        covered = min(self.checkpoint.covered_history_items, len(history_items))
        visible_history = history_items[covered:]
        bounded_history, truncated = self._bound_tool_outputs(visible_history)
        prefix = self._checkpoint_item(intent)
        view: list[AgentHistoryItem] = [prefix, *bounded_history]
        estimated = estimate_context_tokens(intent, view)
        discarded = ["long_tool_output"] if truncated else []
        compressed = bool(self.checkpoint.summary)

        if estimated > self.budget.compaction_threshold:
            cut = self._find_history_cut(history_items, covered)
            if cut > covered:
                summary, summary_usage = await self._summarize(history_items[covered:cut])
                self.checkpoint.summary = summary
                self.checkpoint.covered_history_items = cut
                self.checkpoint.compression_count += 1
                compressed = True
                discarded.extend(_discarded_types(history_items[covered:cut]))
                bounded_history, was_truncated = self._bound_tool_outputs(history_items[cut:])
                if was_truncated:
                    discarded.append("long_tool_output")
                prefix = self._checkpoint_item(intent)
                view = [prefix, *bounded_history]
                estimated = estimate_context_tokens(intent, view)
                if summary_usage is not None:
                    self.metrics.actual_input_tokens += summary_usage.input_tokens
                    self.metrics.output_tokens += summary_usage.output_tokens

        if estimated > self.budget.compaction_threshold:
            bounded_history, hard_truncated = self._bound_tool_outputs(
                history_items[self.checkpoint.covered_history_items :],
                max_characters=max(200, self.budget.max_tool_output_characters // 4),
            )
            if hard_truncated:
                discarded.append("long_tool_output")
            view = [self._checkpoint_item(intent), *bounded_history]
            estimated = estimate_context_tokens(intent, view)

        discarded = _unique(discarded)
        self.checkpoint.discarded_content_types = _unique(
            [*self.checkpoint.discarded_content_types, *discarded]
        )
        return PreparedContext(
            history=view,
            estimated_input_tokens=estimated,
            compressed=compressed,
            discarded_content_types=discarded,
        )

    def record_turn(
        self,
        turn: ModelTurn,
        prepared: PreparedContext,
        *,
        step: int,
        duration_ms: int,
    ) -> None:
        if turn.action.strip():
            _append_unique(self.checkpoint.plan, turn.action.strip())
        usage = turn.usage
        round_metrics = ContextRoundMetrics(
            step=step,
            estimated_input_tokens=prepared.estimated_input_tokens,
            actual_input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            compressed=prepared.compressed,
            discarded_content_types=prepared.discarded_content_types,
            model_duration_ms=duration_ms,
        )
        self.metrics.rounds.append(round_metrics)
        self.metrics.model_turns += 1
        self.metrics.estimated_input_tokens += prepared.estimated_input_tokens
        if usage is not None:
            self.metrics.actual_input_tokens += usage.input_tokens
            self.metrics.output_tokens += usage.output_tokens
        self._sync_metrics()

    def record_tool(self, call: ToolCall, result: ToolResult) -> None:
        self.metrics.tool_calls += 1
        if call.name == "apply_patch" and result.ok:
            path = call.arguments.get("path")
            if path:
                _append_unique(self.checkpoint.modified_files, str(path))
            self.checkpoint.verification_results.clear()
        elif call.name == "run_command":
            if result.ok:
                _append_unique(self.checkpoint.verification_results, result.summary)
            else:
                self.checkpoint.verification_results.clear()

        if result.ok:
            self.checkpoint.unresolved = [
                item for item in self.checkpoint.unresolved if item != result.summary
            ]
        elif result.error is not None:
            _append_unique(self.checkpoint.unresolved, result.error.message)
        else:
            _append_unique(self.checkpoint.unresolved, result.summary)
        self._sync_metrics()

    def record_approval(self, target: str | None, outcome: str) -> None:
        label = target or "unknown target"
        _append_unique(self.checkpoint.approval_decisions, f"{label}: {outcome}")

    def finish(self) -> None:
        self._sync_metrics()

    def _sync_metrics(self) -> None:
        self.metrics.compression_count = self.checkpoint.compression_count
        self.metrics.discarded_content_types = list(
            self.checkpoint.discarded_content_types
        )
        self.metrics.duration_ms = max(0, int((monotonic() - self._started_at) * 1000))

    def _checkpoint_item(self, intent: IntentBrief) -> ContextSummary:
        sections = [
            "[IntentFlow structured context checkpoint]",
            f"Current goal: {intent.goal}",
            "Requirements:\n"
            + "\n".join(
                f"- {item.id}: {item.description}" for item in intent.requirements
            ),
        ]
        if intent.constraints:
            sections.append("User constraints:\n" + "\n".join(f"- {v}" for v in intent.constraints))
        if self.prior_context:
            sections.append("Earlier reviewed session context:\n" + self.prior_context)
        if self.checkpoint.summary:
            sections.append("Earlier run summary:\n" + self.checkpoint.summary)
        if self.checkpoint.plan:
            sections.append(
                "Execution progress:\n"
                + "\n".join(f"- {v}" for v in self.checkpoint.plan[-12:])
            )
        if self.checkpoint.modified_files:
            sections.append(
                "Modified files:\n"
                + "\n".join(f"- {v}" for v in self.checkpoint.modified_files)
            )
        if self.checkpoint.verification_results:
            sections.append(
                "Current valid verification:\n"
                + "\n".join(f"- {v}" for v in self.checkpoint.verification_results)
            )
        if self.checkpoint.approval_decisions:
            sections.append(
                "Approval decisions:\n"
                + "\n".join(f"- {v}" for v in self.checkpoint.approval_decisions[-12:])
            )
        if self.checkpoint.unresolved:
            sections.append(
                "Unresolved issues:\n"
                + "\n".join(f"- {v}" for v in self.checkpoint.unresolved[-12:])
            )
        return ContextSummary(content="\n\n".join(sections))

    def _find_history_cut(
        self,
        history: list[AgentHistoryItem],
        covered: int,
    ) -> int:
        groups = _history_groups(history, covered)
        kept_tokens = 0
        cut = len(history)
        for start, end in reversed(groups):
            group_tokens = estimate_items_tokens(history[start:end])
            if kept_tokens and kept_tokens + group_tokens > self.budget.keep_recent_tokens:
                break
            kept_tokens += group_tokens
            cut = start
        return max(covered, cut)

    async def _summarize(
        self,
        items: Sequence[AgentHistoryItem],
    ) -> tuple[str, ModelUsage | None]:
        transcript = _serialize_history(items)
        if self.summarizer is not None:
            try:
                summary, usage = await self.summarizer.summarize_context(
                    transcript,
                    self.checkpoint.summary,
                )
                summary = summary.strip()
                if summary:
                    return summary[: self.budget.fallback_summary_characters], usage
            except Exception:
                pass
        return self._fallback_summary(items), None

    def _fallback_summary(self, items: Sequence[AgentHistoryItem]) -> str:
        lines = ["Deterministic fallback summary of earlier run history:"]
        for item in items:
            if isinstance(item, ModelTurn):
                lines.append(f"- Model action: {item.action}; result sought: {item.reason}")
            elif isinstance(item, ToolResult):
                status = "ok" if item.ok else "failed"
                lines.append(f"- Tool {item.tool_name} ({status}): {item.summary}")
        summary = "\n".join(lines)
        return summary[-self.budget.fallback_summary_characters :]

    def _bound_tool_outputs(
        self,
        history: Sequence[AgentHistoryItem],
        *,
        max_characters: int | None = None,
    ) -> tuple[list[AgentHistoryItem], bool]:
        limit = max_characters or self.budget.max_tool_output_characters
        result: list[AgentHistoryItem] = []
        truncated = False
        for item in history:
            if not isinstance(item, ToolResult) or len(item.output) <= limit:
                result.append(item)
                continue
            head_size = max(1, (limit * 2) // 3)
            tail_size = max(1, limit - head_size)
            omitted = len(item.output) - head_size - tail_size
            output = (
                item.output[:head_size]
                + f"\n... {omitted} characters omitted by ContextManager ...\n"
                + item.output[-tail_size:]
            )
            result.append(item.model_copy(update={"output": output}))
            truncated = True
        return result, truncated


def estimate_context_tokens(
    intent: IntentBrief,
    history: Sequence[AgentHistoryItem],
) -> int:
    characters = len(intent.model_dump_json()) + sum(len(_item_text(item)) for item in history)
    return max(1, characters // 4)


def estimate_items_tokens(items: Sequence[AgentHistoryItem]) -> int:
    return max(1, sum(len(_item_text(item)) for item in items) // 4)


def _history_groups(
    history: Sequence[AgentHistoryItem],
    start_index: int,
) -> list[tuple[int, int]]:
    groups: list[tuple[int, int]] = []
    start = start_index
    for index in range(start_index, len(history)):
        if index > start and isinstance(history[index], ModelTurn):
            groups.append((start, index))
            start = index
    if start < len(history):
        groups.append((start, len(history)))
    return groups


def _serialize_history(items: Sequence[AgentHistoryItem]) -> str:
    lines: list[str] = []
    for item in items:
        if isinstance(item, ModelTurn):
            calls = ", ".join(call.name for call in item.tool_calls) or "none"
            lines.append(f"[Model] action={item.action}; reason={item.reason}; tools={calls}")
        elif isinstance(item, ToolResult):
            output = item.output[:4_000]
            lines.append(
                f"[Tool result] name={item.tool_name}; ok={item.ok}; "
                f"summary={item.summary}; output={output}"
            )
        else:
            lines.append(f"[Context] {item.content}")
    return "\n".join(lines)


def _item_text(item: AgentHistoryItem) -> str:
    if isinstance(item, ContextSummary):
        return item.content
    payload = item.model_dump()
    if isinstance(item, ModelTurn) and item.provider_items:
        payload["provider_items"] = item.provider_items
    return json.dumps(payload, ensure_ascii=False, default=str)


def _discarded_types(items: Sequence[AgentHistoryItem]) -> list[str]:
    discarded: list[str] = []
    if any(isinstance(item, ModelTurn) for item in items):
        discarded.append("older_model_turns")
    if any(isinstance(item, ToolResult) for item in items):
        discarded.append("older_tool_results")
    return discarded


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))
