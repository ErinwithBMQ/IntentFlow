import os

import pytest

from app.workspaces import WorkspaceAccessError, WorkspaceService


def test_tree_is_stable_and_ignores_generated_directories(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.js").write_text("export const z = 1;", encoding="utf-8")
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.js").write_text("hidden", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("generated", encoding="utf-8")

    tree = WorkspaceService().tree(tmp_path, "todo-demo")

    assert tree.root_name == "todo-demo"
    assert tree.truncated is False
    assert [entry.name for entry in tree.entries] == ["src", "README.md"]
    assert tree.entries[0].children[0].path == "src/z.js"


def test_tree_reports_when_the_entry_limit_is_reached(tmp_path) -> None:
    for index in range(3):
        (tmp_path / f"file-{index}.txt").write_text(str(index), encoding="utf-8")

    tree = WorkspaceService(max_tree_entries=2).tree(tmp_path, "todo-demo")

    assert tree.truncated is True
    assert len(tree.entries) == 2


def test_read_text_rejects_unsafe_and_unsupported_files(tmp_path) -> None:
    (tmp_path / "source.js").write_text("const value = 1;", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"value\x00data")
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    source = WorkspaceService().read_text(tmp_path, "source.js")
    assert source.content == "const value = 1;"
    assert source.language == "javascript"

    with pytest.raises(WorkspaceAccessError, match="工作区") as traversal_error:
        WorkspaceService().read_text(tmp_path, "../outside.txt")
    assert traversal_error.value.kind == "invalid_path"

    with pytest.raises(WorkspaceAccessError) as binary_error:
        WorkspaceService().read_text(tmp_path, "binary.bin")
    assert binary_error.value.kind == "binary"

    with pytest.raises(WorkspaceAccessError) as large_error:
        WorkspaceService(max_text_bytes=4).read_text(tmp_path, "large.txt")
    assert large_error.value.kind == "too_large"


def test_read_text_rejects_a_symlink_that_escapes_the_workspace(tmp_path) -> None:
    outside = tmp_path.parent / "outside-link-target.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "escape.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")

    with pytest.raises(WorkspaceAccessError) as error:
        WorkspaceService().read_text(tmp_path, "escape.txt")

    assert error.value.kind == "invalid_path"


def test_changes_and_file_diff_use_real_file_contents(tmp_path) -> None:
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    (baseline / "same.txt").write_text("same\n", encoding="utf-8")
    (workspace / "same.txt").write_text("same\n", encoding="utf-8")
    (baseline / "modified.txt").write_text("old\nsame\n", encoding="utf-8")
    (workspace / "modified.txt").write_text("new\nsame\n", encoding="utf-8")
    (baseline / "deleted.txt").write_text("gone\n", encoding="utf-8")
    (workspace / "added.txt").write_text("first\nsecond\n", encoding="utf-8")
    (workspace / "image.bin").write_bytes(b"image\x00data")
    (baseline / "dist").mkdir()
    (workspace / "dist").mkdir()
    (baseline / "dist" / "bundle.js").write_text("old", encoding="utf-8")
    (workspace / "dist" / "bundle.js").write_text("new", encoding="utf-8")
    service = WorkspaceService()

    summary = service.changes(baseline, workspace)

    assert [change.path for change in summary.files] == [
        "added.txt",
        "deleted.txt",
        "image.bin",
        "modified.txt",
    ]
    assert summary.changed_files == 4
    assert summary.additions == 3
    assert summary.deletions == 2
    binary_change = next(change for change in summary.files if change.path == "image.bin")
    assert binary_change.viewable is False
    assert binary_change.unavailable_reason == "binary"

    file_diff = service.file_diff(baseline, workspace, "modified.txt")
    assert file_diff.status == "modified"
    assert file_diff.additions == 1
    assert file_diff.deletions == 1
    assert "--- a/modified.txt" in file_diff.diff
    assert "+++ b/modified.txt" in file_diff.diff
    assert "-old" in file_diff.diff
    assert "+new" in file_diff.diff


def test_diff_rejects_unchanged_and_ignored_files(tmp_path) -> None:
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    (baseline / "same.txt").write_text("same", encoding="utf-8")
    (workspace / "same.txt").write_text("same", encoding="utf-8")
    (baseline / "node_modules").mkdir()
    (workspace / "node_modules").mkdir()
    (baseline / "node_modules" / "item.js").write_text("old", encoding="utf-8")
    (workspace / "node_modules" / "item.js").write_text("new", encoding="utf-8")
    service = WorkspaceService()

    assert service.changes(baseline, workspace).changed_files == 0
    with pytest.raises(WorkspaceAccessError) as unchanged_error:
        service.file_diff(baseline, workspace, "same.txt")
    assert unchanged_error.value.kind == "not_found"
    with pytest.raises(WorkspaceAccessError) as ignored_error:
        service.file_diff(baseline, workspace, "node_modules/item.js")
    assert ignored_error.value.kind == "invalid_path"


def test_diff_detects_a_trailing_newline_change(tmp_path) -> None:
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    (baseline / "source.txt").write_bytes(b"value")
    (workspace / "source.txt").write_bytes(b"value\n")

    file_diff = WorkspaceService().file_diff(baseline, workspace, "source.txt")

    assert file_diff.status == "modified"
    assert file_diff.diff
    assert file_diff.additions == 1
    assert file_diff.deletions == 1
