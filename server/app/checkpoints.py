from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.workspaces import ChangeSummary, FileDiff, WorkspaceService


class CheckpointError(RuntimeError):
    """Raised when a direct-workspace checkpoint cannot be persisted or restored."""


class CheckpointConflictError(CheckpointError):
    def __init__(self, conflicting_paths: list[str]) -> None:
        self.conflicting_paths = conflicting_paths
        paths = "、".join(conflicting_paths)
        super().__init__(f"项目文件在 Agent 修改后又发生变化，无法撤销本轮：{paths}")


@dataclass
class CheckpointEntry:
    path: str
    before_exists: bool
    after_exists: bool


class RunCheckpoint:
    def __init__(self, root: Path, project_root: Path) -> None:
        self.root = root.resolve()
        self.project_root = project_root.resolve()
        self.before_root = self.root / "before"
        self.after_root = self.root / "after"
        self.manifest_path = self.root / "manifest.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.entries = self._load_entries()
        if not self.manifest_path.exists():
            self._persist()

    @property
    def paths(self) -> list[str]:
        return sorted(self.entries)

    def apply_text_change(self, relative_path: str, target: Path, updated: str | None) -> None:
        normalized = self._normalize_target(relative_path, target)
        current = target.read_bytes() if target.is_file() else None
        entry = self.entries.get(normalized)
        previous_entry = None if entry is None else CheckpointEntry(**asdict(entry))
        previous_after = (
            self._snapshot_bytes(self.after_root, normalized, entry.after_exists)
            if entry
            else None
        )

        if entry is None:
            entry = CheckpointEntry(
                path=normalized,
                before_exists=current is not None,
                after_exists=current is not None,
            )
            self._write_snapshot(self.before_root, normalized, current)
            self._write_snapshot(self.after_root, normalized, current)
            self.entries[normalized] = entry
            self._persist()
        elif not self._matches_snapshot(target, self.after_root, normalized, entry.after_exists):
            raise CheckpointConflictError([normalized])

        try:
            self._write_project_target(target, updated)
            after = target.read_bytes() if target.is_file() else None
            self._write_snapshot(self.after_root, normalized, after)
            entry.after_exists = after is not None
            self._persist()
        except Exception as error:
            self._write_project_bytes(target, current)
            if previous_entry is None:
                self.entries.pop(normalized, None)
                self._remove_snapshot(self.before_root, normalized)
                self._remove_snapshot(self.after_root, normalized)
            else:
                self.entries[normalized] = previous_entry
                self._write_snapshot(self.after_root, normalized, previous_after)
            self._persist()
            if isinstance(error, CheckpointError):
                raise
            raise CheckpointError(f"无法记录 {normalized} 的 Checkpoint，项目修改已回滚") from error

    def changes(self, service: WorkspaceService) -> ChangeSummary:
        return service.changes_for_paths(self.before_root, self.after_root, self.paths)

    def file_diff(self, service: WorkspaceService, relative_path: str) -> FileDiff:
        if relative_path not in self.entries:
            from app.workspaces import WorkspaceAccessError

            raise WorkspaceAccessError("not_found", "该文件不属于本轮修改")
        return service.file_diff(self.before_root, self.after_root, relative_path)

    def rollback(self, service: WorkspaceService) -> ChangeSummary:
        summary = self.changes(service)
        conflicts = [
            change.path
            for change in summary.files
            if not self._matches_after_state(change.path)
        ]
        if conflicts:
            raise CheckpointConflictError(conflicts)

        current_states: dict[str, bytes | None] = {}
        restored: list[str] = []
        try:
            for change in summary.files:
                target = self._project_target(change.path)
                current_states[change.path] = target.read_bytes() if target.is_file() else None
                entry = self.entries[change.path]
                before = self._snapshot_bytes(
                    self.before_root,
                    change.path,
                    entry.before_exists,
                )
                self._write_project_bytes(target, before)
                restored.append(change.path)
        except Exception as error:
            for path in reversed(restored):
                self._write_project_bytes(self._project_target(path), current_states[path])
            raise CheckpointError("撤销本轮修改时写入失败，已恢复撤销前状态") from error

        for path in restored:
            if current_states[path] is not None and self.entries[path].before_exists is False:
                self._remove_empty_parents(self._project_target(path).parent)
        return summary

    def _load_entries(self) -> dict[str, CheckpointEntry]:
        if not self.manifest_path.is_file():
            return {}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            files = payload.get("files", [])
            entries = [CheckpointEntry(**item) for item in files]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise CheckpointError("Checkpoint 清单损坏，无法恢复运行记录") from error
        return {entry.path: entry for entry in entries}

    def _persist(self) -> None:
        payload = {
            "version": 1,
            "files": [asdict(self.entries[path]) for path in sorted(self.entries)],
        }
        temporary = self.manifest_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.manifest_path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise CheckpointError("无法持久化 Checkpoint 清单") from error

    def _normalize_target(self, relative_path: str, target: Path) -> str:
        normalized = Path(relative_path).as_posix()
        if Path(normalized).is_absolute() or normalized in {"", "."}:
            raise CheckpointError("Checkpoint 文件路径无效")
        expected = self._project_target(normalized)
        if target.resolve() != expected:
            raise CheckpointError("Checkpoint 目标与项目文件不一致")
        return normalized

    def _project_target(self, relative_path: str) -> Path:
        target = (self.project_root / Path(relative_path)).resolve()
        try:
            target.relative_to(self.project_root)
        except ValueError as error:
            raise CheckpointError("Checkpoint 文件路径越过项目目录") from error
        return target

    def _matches_after_state(self, relative_path: str) -> bool:
        entry = self.entries[relative_path]
        return self._matches_snapshot(
            self._project_target(relative_path),
            self.after_root,
            relative_path,
            entry.after_exists,
        )

    @staticmethod
    def _matches_snapshot(
        target: Path,
        snapshot_root: Path,
        relative_path: str,
        expected_exists: bool,
    ) -> bool:
        if expected_exists:
            snapshot = snapshot_root / Path(relative_path)
            return (
                target.is_file()
                and snapshot.is_file()
                and target.read_bytes() == snapshot.read_bytes()
            )
        return not target.exists()

    @staticmethod
    def _snapshot_bytes(root: Path, relative_path: str, exists: bool) -> bytes | None:
        if not exists:
            return None
        target = root / Path(relative_path)
        if not target.is_file():
            raise CheckpointError(f"Checkpoint 文件缺失：{relative_path}")
        return target.read_bytes()

    @staticmethod
    def _write_snapshot(root: Path, relative_path: str, content: bytes | None) -> None:
        target = root / Path(relative_path)
        if content is None:
            target.unlink(missing_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    @staticmethod
    def _remove_snapshot(root: Path, relative_path: str) -> None:
        (root / Path(relative_path)).unlink(missing_ok=True)

    @staticmethod
    def _write_project_target(target: Path, updated: str | None) -> None:
        if updated is None:
            target.unlink()
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8")

    @staticmethod
    def _write_project_bytes(target: Path, content: bytes | None) -> None:
        if content is None:
            target.unlink(missing_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def _remove_empty_parents(self, directory: Path) -> None:
        current = directory
        while current != self.project_root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
