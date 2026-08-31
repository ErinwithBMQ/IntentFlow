from pathlib import Path

import pytest

from app.checkpoints import CheckpointConflictError, RunCheckpoint
from app.workspaces import WorkspaceService


def test_checkpoint_tracks_direct_changes_and_rolls_them_back(tmp_path: Path) -> None:
    project = tmp_path / "project"
    checkpoint_root = tmp_path / "runtime-data" / "runs" / "run-1" / "checkpoint"
    project.mkdir()
    (project / "modified.txt").write_text("before\n", encoding="utf-8")
    (project / "deleted.txt").write_text("restore me\n", encoding="utf-8")
    checkpoint = RunCheckpoint(checkpoint_root, project)

    checkpoint.apply_text_change(
        "modified.txt",
        project / "modified.txt",
        "after\n",
    )
    checkpoint.apply_text_change(
        "created.txt",
        project / "created.txt",
        "new\n",
    )
    checkpoint.apply_text_change(
        "deleted.txt",
        project / "deleted.txt",
        None,
    )

    restored = RunCheckpoint(checkpoint_root, project)
    service = WorkspaceService()
    summary = restored.changes(service)

    assert [(change.path, change.status) for change in summary.files] == [
        ("created.txt", "added"),
        ("deleted.txt", "deleted"),
        ("modified.txt", "modified"),
    ]
    assert "+after" in restored.file_diff(service, "modified.txt").diff

    restored.rollback(service)

    assert (project / "modified.txt").read_text(encoding="utf-8") == "before\n"
    assert (project / "deleted.txt").read_text(encoding="utf-8") == "restore me\n"
    assert not (project / "created.txt").exists()
    assert restored.changes(service).changed_files == 3


def test_checkpoint_blocks_rollback_after_external_file_change(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "source.txt"
    target.write_text("before", encoding="utf-8")
    checkpoint = RunCheckpoint(tmp_path / "checkpoint", project)
    checkpoint.apply_text_change("source.txt", target, "agent")
    target.write_text("external", encoding="utf-8")

    with pytest.raises(CheckpointConflictError, match="source.txt"):
        checkpoint.rollback(WorkspaceService())

    assert target.read_text(encoding="utf-8") == "external"


def test_checkpoint_blocks_later_agent_patch_after_external_file_change(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "source.txt"
    target.write_text("before", encoding="utf-8")
    checkpoint = RunCheckpoint(tmp_path / "checkpoint", project)
    checkpoint.apply_text_change("source.txt", target, "agent")
    target.write_text("external", encoding="utf-8")

    with pytest.raises(CheckpointConflictError, match="source.txt"):
        checkpoint.apply_text_change("source.txt", target, "second agent edit")

    assert target.read_text(encoding="utf-8") == "external"
