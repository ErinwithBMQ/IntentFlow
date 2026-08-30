from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agent.models import IntentBrief
from app.intent.models import IntentCanvas
from app.runs import RunSnapshot

ConversationMode = Literal["ask", "plan", "agent"]
ApprovalMode = Literal["ask", "auto"]
MessageRole = Literal["user", "assistant"]


class ProjectRecord(BaseModel):
    id: str
    name: str
    relative_path: str


class SessionRecord(BaseModel):
    id: str
    project_id: str
    title: str
    approval_mode: ApprovalMode = "ask"
    created_at: str
    updated_at: str


class CanvasSnapshotRecord(BaseModel):
    id: str
    session_id: str
    canvas: IntentCanvas
    created_at: str


class ConversationMessage(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    mode: ConversationMode
    content: str
    canvas_snapshot_id: str | None = None
    run_id: str | None = None
    intent: IntentBrief | None = None
    created_at: str
    sequence: int


class SessionDetail(BaseModel):
    session: SessionRecord
    messages: list[ConversationMessage] = Field(default_factory=list)
    canvas_snapshots: list[CanvasSnapshotRecord] = Field(default_factory=list)
    runs: list[RunSnapshot] = Field(default_factory=list)


class SessionStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def ensure_project(self, project: ProjectRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (id, name, relative_path)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  relative_path = excluded.relative_path
                """,
                (project.id, project.name, project.relative_path),
            )

    def create_session(self, project_id: str, title: str = "新对话") -> SessionRecord:
        now = _now()
        session = SessionRecord(
            id=f"session-{uuid4().hex[:12]}",
            project_id=project_id,
            title=title.strip() or "新对话",
            approval_mode="ask",
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                  id, project_id, title, approval_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.project_id,
                    session.title,
                    session.approval_mode,
                    session.created_at,
                    session.updated_at,
                ),
            )
        return session

    def set_approval_mode(self, session_id: str, approval_mode: ApprovalMode) -> SessionRecord:
        now = _now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET approval_mode = ?, updated_at = ? WHERE id = ?",
                (approval_mode, now, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def list_sessions(self, project_id: str | None = None) -> list[SessionRecord]:
        query = "SELECT * FROM sessions"
        parameters: tuple[str, ...] = ()
        if project_id is not None:
            query += " WHERE project_id = ?"
            parameters = (project_id,)
        query += " ORDER BY updated_at DESC, created_at DESC"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row is not None else None

    def get_detail(self, session_id: str) -> SessionDetail | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        with self._lock, self._connect() as connection:
            message_rows = connection.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
            canvas_rows = connection.execute(
                "SELECT * FROM canvas_snapshots WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
            run_rows = connection.execute(
                "SELECT snapshot_json FROM runs WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return SessionDetail(
            session=session,
            messages=[_message_from_row(row) for row in message_rows],
            canvas_snapshots=[_canvas_from_row(row) for row in canvas_rows],
            runs=[RunSnapshot.model_validate_json(row["snapshot_json"]) for row in run_rows],
        )

    def get_pending_review_run(self, session_id: str) -> RunSnapshot | None:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_json FROM runs WHERE session_id = ? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        snapshots = [RunSnapshot.model_validate_json(row["snapshot_json"]) for row in rows]
        return next(
            (snapshot for snapshot in snapshots if snapshot.review_status == "pending"),
            None,
        )

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if exists is None:
                return False
            connection.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True

    def add_canvas_snapshot(self, session_id: str, canvas: IntentCanvas) -> CanvasSnapshotRecord:
        snapshot = CanvasSnapshotRecord(
            id=f"canvas-{uuid4().hex[:12]}",
            session_id=session_id,
            canvas=canvas,
            created_at=_now(),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO canvas_snapshots (id, session_id, canvas_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.session_id,
                    snapshot.canvas.model_dump_json(),
                    snapshot.created_at,
                ),
            )
        return snapshot

    def add_message(
        self,
        session_id: str,
        role: MessageRole,
        mode: ConversationMode,
        content: str,
        *,
        canvas_snapshot_id: str | None = None,
        run_id: str | None = None,
        intent: IntentBrief | None = None,
    ) -> ConversationMessage:
        with self._lock, self._connect() as connection:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            now = _now()
            message = ConversationMessage(
                id=f"message-{uuid4().hex[:12]}",
                session_id=session_id,
                role=role,
                mode=mode,
                content=content,
                canvas_snapshot_id=canvas_snapshot_id,
                run_id=run_id,
                intent=intent,
                created_at=now,
                sequence=sequence,
            )
            connection.execute(
                """
                INSERT INTO messages (
                  id, session_id, role, mode, content, canvas_snapshot_id,
                  run_id, intent_json, created_at, sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    session_id,
                    role,
                    mode,
                    content,
                    canvas_snapshot_id,
                    run_id,
                    intent.model_dump_json() if intent else None,
                    now,
                    sequence,
                ),
            )
            if role == "user" and sequence == 1:
                connection.execute(
                    "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                    (_short_title(content), now, session_id),
                )
            else:
                connection.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (now, session_id),
                )
        return message

    def attach_run(self, message_id: str, run_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE messages SET run_id = ? WHERE id = ?",
                (run_id, message_id),
            )

    def save_run(self, snapshot: RunSnapshot) -> None:
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                  id, session_id, trigger_message_id, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  session_id = excluded.session_id,
                  trigger_message_id = excluded.trigger_message_id,
                  snapshot_json = excluded.snapshot_json,
                  updated_at = excluded.updated_at
                """,
                (
                    snapshot.id,
                    snapshot.session_id,
                    snapshot.trigger_message_id,
                    snapshot.model_dump_json(),
                    now,
                    now,
                ),
            )

    def load_runs(self) -> list[RunSnapshot]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT snapshot_json FROM runs ORDER BY created_at",
            ).fetchall()
        return [RunSnapshot.model_validate_json(row["snapshot_json"]) for row in rows]

    def build_run_context(
        self,
        session_id: str,
        *,
        before_sequence: int | None = None,
        max_characters: int = 12_000,
    ) -> str:
        detail = self.get_detail(session_id)
        if detail is None:
            return ""

        messages = [
            message
            for message in detail.messages
            if before_sequence is None or message.sequence < before_sequence
        ]
        message_lines = [
            f"- {message.role}/{message.mode}: {' '.join(message.content.split())[:500]}"
            for message in messages[-12:]
        ]
        if len(messages) > 12:
            message_lines.insert(0, f"- {len(messages) - 12} earlier messages compacted")

        reviewed_runs = [run for run in detail.runs if run.review_status != "pending"][-6:]
        run_lines: list[str] = []
        for run in reviewed_runs:
            review = "applied to project" if run.review_status == "accepted" else "discarded"
            summary = run.report.summary if run.report else "No final report"
            files = run.context_checkpoint.modified_files if run.context_checkpoint else []
            evidence = run.context_checkpoint.verification_results if run.context_checkpoint else []
            run_lines.append(
                f"- {run.id}: {review}; {summary}; files={files}; verification={evidence}"
            )

        sections: list[str] = []
        if message_lines:
            sections.append("Recent session conversation:\n" + "\n".join(message_lines))
        if run_lines:
            sections.append("Reviewed Agent runs:\n" + "\n".join(run_lines))
        return "\n\n".join(sections)[-max_characters:]

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  relative_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL REFERENCES projects(id),
                  title TEXT NOT NULL,
                  approval_mode TEXT NOT NULL DEFAULT 'ask',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canvas_snapshots (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  canvas_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  mode TEXT NOT NULL,
                  content TEXT NOT NULL,
                  canvas_snapshot_id TEXT REFERENCES canvas_snapshots(id),
                  run_id TEXT,
                  intent_json TEXT,
                  created_at TEXT NOT NULL,
                  sequence INTEGER NOT NULL,
                  UNIQUE(session_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY,
                  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                  trigger_message_id TEXT,
                  snapshot_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            session_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sessions)")
            }
            if "approval_mode" not in session_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN approval_mode TEXT NOT NULL DEFAULT 'ask'"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        approval_mode=row["approval_mode"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: sqlite3.Row) -> ConversationMessage:
    return ConversationMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        mode=row["mode"],
        content=row["content"],
        canvas_snapshot_id=row["canvas_snapshot_id"],
        run_id=row["run_id"],
        intent=IntentBrief.model_validate_json(row["intent_json"]) if row["intent_json"] else None,
        created_at=row["created_at"],
        sequence=row["sequence"],
    )


def _canvas_from_row(row: sqlite3.Row) -> CanvasSnapshotRecord:
    return CanvasSnapshotRecord(
        id=row["id"],
        session_id=row["session_id"],
        canvas=IntentCanvas.model_validate_json(row["canvas_json"]),
        created_at=row["created_at"],
    )


def _short_title(content: str) -> str:
    normalized = " ".join(content.split())
    return normalized if len(normalized) <= 28 else f"{normalized[:27]}…"


def _now() -> str:
    return datetime.now(UTC).isoformat()
