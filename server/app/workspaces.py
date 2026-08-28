from __future__ import annotations

import difflib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_IGNORED_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".vite",
        "__pycache__",
        "coverage",
        "dist",
        "node_modules",
    }
)
DEFAULT_MAX_TEXT_BYTES = 512_000
DEFAULT_MAX_TREE_ENTRIES = 2_000
DEFAULT_MAX_DIFF_FILES = 2_000

WorkspaceErrorKind = Literal[
    "binary",
    "invalid_path",
    "invalid_utf8",
    "not_file",
    "not_found",
    "too_large",
    "too_many_files",
]
ChangeKind = Literal["added", "modified", "deleted"]


class WorkspaceAccessError(Exception):
    def __init__(self, kind: WorkspaceErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class WorkspaceEntry(BaseModel):
    name: str
    path: str
    kind: Literal["directory", "file"]
    children: list[WorkspaceEntry] = Field(default_factory=list)


class WorkspaceTree(BaseModel):
    root_name: str
    entries: list[WorkspaceEntry]
    truncated: bool = False


class WorkspaceFile(BaseModel):
    path: str
    content: str
    size: int
    language: str


class FileChange(BaseModel):
    path: str
    status: ChangeKind
    additions: int = 0
    deletions: int = 0
    viewable: bool = True
    unavailable_reason: Literal["binary", "invalid_utf8", "too_large"] | None = None


class ChangeSummary(BaseModel):
    files: list[FileChange]
    changed_files: int
    additions: int
    deletions: int


class FileDiff(FileChange):
    diff: str


class WorkspaceService:
    def __init__(
        self,
        *,
        ignored_names: frozenset[str] = DEFAULT_IGNORED_NAMES,
        max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES,
        max_tree_entries: int = DEFAULT_MAX_TREE_ENTRIES,
        max_diff_files: int = DEFAULT_MAX_DIFF_FILES,
    ) -> None:
        self.ignored_names = ignored_names
        self._ignored_names_casefold = frozenset(name.casefold() for name in ignored_names)
        self.max_text_bytes = max_text_bytes
        self.max_tree_entries = max_tree_entries
        self.max_diff_files = max_diff_files

    def tree(self, root: Path, root_name: str) -> WorkspaceTree:
        resolved_root = self._workspace_root(root)
        entry_count = 0
        truncated = False

        def visit(directory: Path) -> list[WorkspaceEntry]:
            nonlocal entry_count, truncated
            entries: list[WorkspaceEntry] = []
            try:
                children = sorted(
                    directory.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.casefold(), item.name),
                )
            except OSError as error:
                raise WorkspaceAccessError("not_found", "工作区目录无法读取") from error

            for child in children:
                if (
                    self._is_ignored(child.name)
                    or child.is_symlink()
                    or not self._is_within_root(resolved_root, child)
                ):
                    continue
                if entry_count >= self.max_tree_entries:
                    truncated = True
                    break

                try:
                    if child.is_dir():
                        kind: Literal["directory", "file"] = "directory"
                    elif child.is_file():
                        kind = "file"
                    else:
                        continue
                except OSError:
                    continue

                entry_count += 1
                relative_path = child.relative_to(resolved_root).as_posix()
                entries.append(
                    WorkspaceEntry(
                        name=child.name,
                        path=relative_path,
                        kind=kind,
                        children=visit(child) if kind == "directory" else [],
                    )
                )
                if truncated:
                    break
            return entries

        return WorkspaceTree(
            root_name=root_name,
            entries=visit(resolved_root),
            truncated=truncated,
        )

    def read_text(self, root: Path, relative_path: str) -> WorkspaceFile:
        target, normalized_path = self._resolve_path(root, relative_path)
        if not target.exists():
            raise WorkspaceAccessError("not_found", "文件不存在")
        if not target.is_file():
            raise WorkspaceAccessError("not_file", "目标不是文件")

        content = self._read_text_file(target)
        return WorkspaceFile(
            path=normalized_path,
            content=content,
            size=target.stat().st_size,
            language=self._language_for(target),
        )

    def changes(self, baseline_root: Path, workspace_root: Path) -> ChangeSummary:
        baseline_files = self._collect_files(baseline_root)
        workspace_files = self._collect_files(workspace_root)
        changes: list[FileChange] = []

        for relative_path in sorted(set(baseline_files) | set(workspace_files)):
            before = baseline_files.get(relative_path)
            after = workspace_files.get(relative_path)
            if before is not None and after is not None and self._files_equal(before, after):
                continue
            changes.append(self._build_change(relative_path, before, after))

        return ChangeSummary(
            files=changes,
            changed_files=len(changes),
            additions=sum(change.additions for change in changes),
            deletions=sum(change.deletions for change in changes),
        )

    def file_diff(
        self,
        baseline_root: Path,
        workspace_root: Path,
        relative_path: str,
    ) -> FileDiff:
        baseline_target, normalized_path = self._resolve_path(
            baseline_root,
            relative_path,
            require_exists=False,
        )
        workspace_target, _ = self._resolve_path(
            workspace_root,
            relative_path,
            require_exists=False,
        )
        before = baseline_target if baseline_target.is_file() else None
        after = workspace_target if workspace_target.is_file() else None
        if before is None and after is None:
            raise WorkspaceAccessError("not_found", "变更文件不存在")
        if before is not None and after is not None and self._files_equal(before, after):
            raise WorkspaceAccessError("not_found", "该文件没有变更")

        change = self._build_change(normalized_path, before, after)
        diff = self._create_diff(normalized_path, before, after)[0] if change.viewable else ""
        return FileDiff(**change.model_dump(), diff=diff)

    def _build_change(
        self,
        relative_path: str,
        before: Path | None,
        after: Path | None,
    ) -> FileChange:
        if before is None:
            status: ChangeKind = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "modified"

        try:
            _, additions, deletions = self._create_diff(relative_path, before, after)
        except WorkspaceAccessError as error:
            if error.kind not in {"binary", "invalid_utf8", "too_large"}:
                raise
            return FileChange(
                path=relative_path,
                status=status,
                viewable=False,
                unavailable_reason=error.kind,
            )

        return FileChange(
            path=relative_path,
            status=status,
            additions=additions,
            deletions=deletions,
        )

    def _create_diff(
        self,
        relative_path: str,
        before: Path | None,
        after: Path | None,
    ) -> tuple[str, int, int]:
        before_content = self._read_text_file(before) if before is not None else ""
        after_content = self._read_text_file(after) if after is not None else ""
        lines = list(
            difflib.unified_diff(
                before_content.splitlines(keepends=True),
                after_content.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        additions = sum(
            1 for line in lines if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1 for line in lines if line.startswith("-") and not line.startswith("---")
        )
        diff = "\n".join(line.rstrip("\r\n") for line in lines)
        if diff:
            diff += "\n"
        return diff, additions, deletions

    def _collect_files(self, root: Path) -> dict[str, Path]:
        resolved_root = self._workspace_root(root)
        files: dict[str, Path] = {}
        pending = [resolved_root]
        while pending:
            directory = pending.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name, reverse=True)
            except OSError as error:
                raise WorkspaceAccessError("not_found", "工作区目录无法读取") from error

            for child in children:
                if (
                    self._is_ignored(child.name)
                    or child.is_symlink()
                    or not self._is_within_root(resolved_root, child)
                ):
                    continue
                if child.is_dir():
                    pending.append(child)
                elif child.is_file():
                    relative_path = child.relative_to(resolved_root).as_posix()
                    files[relative_path] = child
                    if len(files) > self.max_diff_files:
                        raise WorkspaceAccessError(
                            "too_many_files",
                            "工作区文件数量超过 Diff 限制",
                        )
        return files

    def _workspace_root(self, root: Path) -> Path:
        try:
            resolved_root = root.resolve(strict=True)
        except OSError as error:
            raise WorkspaceAccessError("not_found", "工作区不存在") from error
        if not resolved_root.is_dir():
            raise WorkspaceAccessError("not_found", "工作区不存在")
        return resolved_root

    def _resolve_path(
        self,
        root: Path,
        relative_path: str,
        *,
        require_exists: bool = True,
    ) -> tuple[Path, str]:
        path = Path(relative_path)
        if not relative_path.strip() or path.is_absolute() or ".." in path.parts:
            raise WorkspaceAccessError("invalid_path", "只允许访问工作区内的相对路径")
        if any(self._is_ignored(part) for part in path.parts):
            raise WorkspaceAccessError("invalid_path", "该路径不允许访问")

        resolved_root = self._workspace_root(root)
        target = (resolved_root / path).resolve(strict=False)
        try:
            normalized_path = target.relative_to(resolved_root).as_posix()
        except ValueError as error:
            raise WorkspaceAccessError("invalid_path", "路径超出工作区范围") from error
        if require_exists and not target.exists():
            raise WorkspaceAccessError("not_found", "文件不存在")
        return target, normalized_path

    def _read_text_file(self, target: Path) -> str:
        try:
            size = target.stat().st_size
        except OSError as error:
            raise WorkspaceAccessError("not_found", "文件不存在") from error
        if size > self.max_text_bytes:
            raise WorkspaceAccessError("too_large", "文件超过可查看大小限制")

        try:
            content = target.read_bytes()
        except OSError as error:
            raise WorkspaceAccessError("not_found", "文件无法读取") from error
        if b"\x00" in content:
            raise WorkspaceAccessError("binary", "二进制文件不能作为文本查看")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceAccessError("invalid_utf8", "文件不是有效的 UTF-8 文本") from error

    @staticmethod
    def _is_within_root(root: Path, target: Path) -> bool:
        try:
            target.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            return False
        return True

    def _is_ignored(self, name: str) -> bool:
        return name.casefold() in self._ignored_names_casefold

    @staticmethod
    def _files_equal(left: Path, right: Path) -> bool:
        if left.stat().st_size != right.stat().st_size:
            return False
        with left.open("rb") as left_file, right.open("rb") as right_file:
            while True:
                left_chunk = left_file.read(64 * 1024)
                right_chunk = right_file.read(64 * 1024)
                if left_chunk != right_chunk:
                    return False
                if not left_chunk:
                    return True

    @staticmethod
    def _language_for(path: Path) -> str:
        return {
            ".css": "css",
            ".html": "html",
            ".js": "javascript",
            ".json": "json",
            ".jsx": "jsx",
            ".md": "markdown",
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "tsx",
        }.get(path.suffix.lower(), "text")
