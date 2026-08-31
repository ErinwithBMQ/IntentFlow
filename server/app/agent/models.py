from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

VerificationStatus = Literal[
    "not_configured",
    "command_start_failed",
    "failed",
    "passed",
]


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
    provider_items: list[Any] = Field(default_factory=list, exclude=True)
    usage: ModelUsage | None = None


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ToolResult(BaseModel):
    call_id: str
    tool_name: str
    ok: bool
    summary: str
    output: str = ""
    error: ToolError | None = None
    verification_status: VerificationStatus | None = None


class ToolError(BaseModel):
    kind: Literal[
        "invalid_arguments",
        "path_error",
        "not_found",
        "conflict",
        "io_error",
        "command_not_configured",
        "command_start_failed",
        "verification_failed",
        "timeout",
        "cancelled",
        "user_rejected",
        "unknown_tool",
    ]
    message: str
    retryable: bool
    suggestion: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ContextSummary(BaseModel):
    content: str


class ContextCheckpoint(BaseModel):
    summary: str = ""
    covered_history_items: int = 0
    current_goal: str = ""
    constraints: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    verification_results: list[str] = Field(default_factory=list)
    approval_decisions: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    compression_count: int = 0
    discarded_content_types: list[str] = Field(default_factory=list)


class ContextRoundMetrics(BaseModel):
    step: int
    estimated_input_tokens: int
    actual_input_tokens: int | None = None
    output_tokens: int | None = None
    compressed: bool = False
    discarded_content_types: list[str] = Field(default_factory=list)
    model_duration_ms: int = 0


class RunMetrics(BaseModel):
    model_turns: int = 0
    tool_calls: int = 0
    estimated_input_tokens: int = 0
    actual_input_tokens: int = 0
    output_tokens: int = 0
    compression_count: int = 0
    discarded_content_types: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    rounds: list[ContextRoundMetrics] = Field(default_factory=list)


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
    verification_status: VerificationStatus | None = None
    approval_id: str | None = None
    patch: str | None = None
    approval_status: Literal["approval_required", "approved", "rejected", "cancelled"] | None = None


class RunResult(BaseModel):
    status: Literal["completed", "partial", "failed", "stopped"]
    report: RunReport
    events: list[RunEvent]
    steps: int


AgentHistoryItem = ModelTurn | ToolResult | ContextSummary
