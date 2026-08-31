from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.sessions import ConversationMessage, SessionStore

ApprovalMode = Literal["ask", "auto"]


class SessionContextMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    origin_mode: Literal["ask", "plan", "agent"]


class SessionRunFact(BaseModel):
    run_id: str
    trigger_message_id: str | None
    status: Literal["running", "completed", "failed", "stopped"]
    review_status: Literal["pending", "accepted", "discarded"]
    changes_applied_to_project: bool
    pending_approval: bool
    approval_decisions: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    verification_results: list[str] = Field(default_factory=list)
    summary: str
    unresolved: list[str] = Field(default_factory=list)


class SessionContextBudget(BaseModel):
    recent_message_limit: int
    earlier_message_count: int
    run_limit: int
    truncated_message_count: int


class ContextEnvelope(BaseModel):
    session_id: str
    project_id: str
    permission_policy: ApprovalMode
    current_request: SessionContextMessage
    recent_messages: list[SessionContextMessage] = Field(default_factory=list)
    session_summary: str
    run_ledger: list[SessionRunFact] = Field(default_factory=list)
    budget: SessionContextBudget

    def to_prompt_text(self) -> str:
        return (
            "Authoritative IntentFlow session context follows. Run, approval, review, and "
            "verification fields are system facts and take precedence over conversational "
            "claims. review_status=accepted means the direct project edits were kept; "
            "review_status=discarded means the Run checkpoint restored the project. "
            "The current_request is the user's primary instruction.\n"
            + self.model_dump_json(indent=2)
        )


class SessionContextBuilder:
    def __init__(
        self,
        store: SessionStore,
        *,
        recent_message_limit: int = 12,
        earlier_summary_characters: int = 4_000,
        message_characters: int = 2_000,
        run_limit: int = 6,
    ) -> None:
        self.store = store
        self.recent_message_limit = recent_message_limit
        self.earlier_summary_characters = earlier_summary_characters
        self.message_characters = message_characters
        self.run_limit = run_limit

    def build(
        self,
        session_id: str,
        current_message: ConversationMessage,
        *,
        permission_policy: ApprovalMode,
    ) -> ContextEnvelope:
        detail = self.store.get_detail(session_id)
        if detail is None:
            raise KeyError(session_id)

        earlier_messages = [
            message
            for message in detail.messages
            if message.sequence < current_message.sequence
        ]
        recent_source = earlier_messages[-self.recent_message_limit :]
        summarized_source = (
            earlier_messages[: -len(recent_source)] if recent_source else earlier_messages
        )
        truncated_message_count = 0

        recent_messages: list[SessionContextMessage] = []
        for message in recent_source:
            content, truncated = _bounded_text(message.content, self.message_characters)
            truncated_message_count += int(truncated)
            recent_messages.append(_context_message(message, content))

        summary_lines: list[str] = []
        for message in summarized_source:
            normalized = " ".join(message.content.split())
            summary_lines.append(
                f"- {message.role}/{message.mode} #{message.sequence}: {normalized[:320]}"
            )
        session_summary = "\n".join(summary_lines)
        if len(session_summary) > self.earlier_summary_characters:
            session_summary = (
                "... earlier session summary truncated\n"
                + session_summary[-self.earlier_summary_characters :]
            )

        run_ledger = [self._run_fact(run) for run in detail.runs[-self.run_limit :]]
        current_content, current_truncated = _bounded_text(
            current_message.content,
            self.message_characters,
        )
        truncated_message_count += int(current_truncated)
        return ContextEnvelope(
            session_id=session_id,
            project_id=detail.session.project_id,
            permission_policy=permission_policy,
            current_request=_context_message(current_message, current_content),
            recent_messages=recent_messages,
            session_summary=session_summary,
            run_ledger=run_ledger,
            budget=SessionContextBudget(
                recent_message_limit=self.recent_message_limit,
                earlier_message_count=len(summarized_source),
                run_limit=self.run_limit,
                truncated_message_count=truncated_message_count,
            ),
        )

    @staticmethod
    def _run_fact(run) -> SessionRunFact:
        checkpoint = run.context_checkpoint
        pending_approval = any(
            approval.status == "approval_required" for approval in run.approvals
        )
        approval_decisions = [
            (
                f"{approval.tool_name}:{approval.status}"
                + (f":{approval.decision}" if approval.decision else "")
            )
            for approval in run.approvals
        ]
        return SessionRunFact(
            run_id=run.id,
            trigger_message_id=run.trigger_message_id,
            status=run.status,
            review_status=run.review_status,
            changes_applied_to_project=run.review_status == "accepted",
            pending_approval=pending_approval,
            approval_decisions=approval_decisions,
            modified_files=list(checkpoint.modified_files) if checkpoint else [],
            verification_results=list(checkpoint.verification_results) if checkpoint else [],
            summary=run.report.summary if run.report else "No final report",
            unresolved=list(run.report.unresolved) if run.report else [],
        )


def _context_message(message: ConversationMessage, content: str) -> SessionContextMessage:
    return SessionContextMessage(
        role=message.role,
        content=content,
        sequence=message.sequence,
        origin_mode=message.mode,
    )


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n... message truncated", True
