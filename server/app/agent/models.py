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


class ToolApproval(BaseModel):
    id: str
    tool_call_id: str
    tool_name: str
    target: str | None = None
    reason: str
    patch: str
    status: Literal["approval_required", "approved", "rejected", "cancelled"]
    decision: Literal["allow_once", "allow_for_run", "reject"] | None = None


class RequirementClaim(BaseModel):
    requirement_id: str
    status: Literal["verified", "implemented", "failed", "unresolved"]
    summary: str


class RequirementResult(BaseModel):
    requirement_id: str
    status: Literal["verified", "implemented", "failed", "unresolved"]
    summary: str
    related_files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class RunReport(BaseModel):
    status: Literal["completed", "partial", "failed"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    requirement_results: list[RequirementResult] = Field(default_factory=list)


class RunEvent(BaseModel):
    sequence: int
    kind: Literal[
        "run_started",
        "model_turn",
        "approval_required",
        "approval_resolved",
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
    approval_id: str | None = None
    patch: str | None = None
    approval_status: Literal["approval_required", "approved", "rejected", "cancelled"] | None = None


class RunResult(BaseModel):
    status: Literal["completed", "partial", "failed", "stopped"]
    report: RunReport
    events: list[RunEvent]
    steps: int


AgentHistoryItem = ModelTurn | ToolResult
