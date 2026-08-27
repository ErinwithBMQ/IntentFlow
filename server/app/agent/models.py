from typing import Any, Literal

from pydantic import BaseModel, Field


class IntentRequirement(BaseModel):
    id: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class IntentBrief(BaseModel):
    title: str
    goal: str
    requirements: list[IntentRequirement]
    constraints: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    action: str = ""
    reason: str = ""
    related_requirement_ids: list[str] = Field(default_factory=list)


class ModelTurn(BaseModel):
    action: str
    reason: str
    related_requirement_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolResult(BaseModel):
    call_id: str
    tool_name: str
    ok: bool
    summary: str
    output: str = ""


class RunReport(BaseModel):
    status: Literal["completed", "partial", "failed"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class RunEvent(BaseModel):
    sequence: int
    kind: Literal[
        "run_started",
        "model_turn",
        "tool_started",
        "tool_finished",
        "run_finished",
    ]
    phase: Literal["planning", "acting", "verifying", "finished"]
    status: Literal["running", "succeeded", "failed", "stopped"]
    action: str
    reason: str
    related_requirement_ids: list[str] = Field(default_factory=list)
    tool_name: str | None = None
    target: str | None = None
    evidence: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    status: Literal["completed", "partial", "failed", "stopped"]
    report: RunReport
    events: list[RunEvent]
    steps: int


AgentHistoryItem = ModelTurn | ToolResult
