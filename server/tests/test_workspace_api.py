import shutil
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.runs import RunManager, RunRecord
from app.workspaces import WorkspaceService


def prepare_repository(root: Path) -> tuple[RunManager, RunRecord]:
    project = root / "examples" / "todo-demo"
    project.mkdir(parents=True)
    (project / "source.js").write_bytes(b"const value = 'before';\n")
    (project / "README.md").write_bytes(b"demo\n")
    run_root = root / "runtime-data" / "runs" / "run-1"
    baseline = run_root / "baseline" / "todo-demo"
    workspace = run_root / "todo-demo"
    shutil.copytree(project, baseline)
    shutil.copytree(baseline, workspace)
    (workspace / "source.js").write_bytes(b"const value = 'after';\n")
    (workspace / "added.txt").write_bytes(b"new\n")
    (workspace / "README.md").unlink()

    manager = RunManager(root)
    record = RunRecord(
        "run-1",
        workspace,
        baseline,
        "runtime-data/runs/run-1/todo-demo",
    )
    record.status = "completed"
    manager.records[record.id] = record
    return manager, record


async def test_workspace_api_reads_project_run_and_diff(tmp_path, monkeypatch) -> None:
    manager, _ = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        project_tree = await client.get("/api/project/tree")
        project_file = await client.get("/api/project/file", params={"path": "source.js"})
        run_tree = await client.get("/api/runs/run-1/tree")
        run_file = await client.get("/api/runs/run-1/file", params={"path": "source.js"})
        changes = await client.get("/api/runs/run-1/changes")
        file_diff = await client.get(
            "/api/runs/run-1/diff",
            params={"path": "source.js"},
        )

    assert project_tree.status_code == 200
    assert [entry["name"] for entry in project_tree.json()["entries"]] == [
        "README.md",
        "source.js",
    ]
    assert project_file.json()["content"] == "const value = 'before';\n"
    assert run_tree.status_code == 200
    assert run_file.json()["content"] == "const value = 'after';\n"
    assert changes.json()["changed_files"] == 3
    assert [item["path"] for item in changes.json()["files"]] == [
        "README.md",
        "added.txt",
        "source.js",
    ]
    assert file_diff.status_code == 200
    assert "-const value = 'before';" in file_diff.json()["diff"]
    assert "+const value = 'after';" in file_diff.json()["diff"]


async def test_workspace_api_rejects_invalid_state_and_paths(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        traversal = await client.get(
            "/api/project/file",
            params={"path": "../secret.txt"},
        )
        missing_run = await client.get("/api/runs/missing/tree")
        record.status = "running"
        running_diff = await client.get("/api/runs/run-1/changes")

    assert traversal.status_code == 400
    assert missing_run.status_code == 404
    assert running_diff.status_code == 409


async def test_accept_applies_all_changes_and_is_idempotent(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        accepted = await client.post("/api/runs/run-1/accept")
        accepted_again = await client.post("/api/runs/run-1/accept")
        discard_after_accept = await client.post("/api/runs/run-1/discard")
        preserved_diff = await client.get("/api/runs/run-1/changes")

    project = tmp_path / "examples" / "todo-demo"
    assert accepted.status_code == 200
    assert accepted.json()["review_status"] == "accepted"
    assert accepted_again.status_code == 200
    assert accepted_again.json()["review_status"] == "accepted"
    assert discard_after_accept.status_code == 409
    assert record.review_status == "accepted"
    assert (project / "source.js").read_text(encoding="utf-8") == "const value = 'after';\n"
    assert (project / "added.txt").read_text(encoding="utf-8") == "new\n"
    assert not (project / "README.md").exists()
    assert preserved_diff.json()["changed_files"] == 3


async def test_accept_rejects_project_conflicts_without_partial_write(
    tmp_path,
    monkeypatch,
) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    project = tmp_path / "examples" / "todo-demo"
    (project / "source.js").write_text("changed outside the run\n", encoding="utf-8")
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/runs/run-1/accept")

    assert response.status_code == 409
    assert "source.js" in response.json()["detail"]
    assert record.review_status == "pending"
    assert (project / "source.js").read_text(encoding="utf-8") == "changed outside the run\n"
    assert not (project / "added.txt").exists()
    assert (project / "README.md").is_file()


async def test_discard_preserves_project_and_blocks_later_accept(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        discarded = await client.post("/api/runs/run-1/discard")
        discarded_again = await client.post("/api/runs/run-1/discard")
        accept_after_discard = await client.post("/api/runs/run-1/accept")

    project = tmp_path / "examples" / "todo-demo"
    assert discarded.status_code == 200
    assert discarded_again.status_code == 200
    assert discarded.json()["review_status"] == "discarded"
    assert record.review_status == "discarded"
    assert accept_after_discard.status_code == 409
    assert (project / "source.js").read_text(encoding="utf-8") == "const value = 'before';\n"
    assert not (project / "added.txt").exists()
    assert (project / "README.md").is_file()


async def test_only_completed_runs_can_be_accepted(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    record.status = "failed"
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        rejected = await client.post("/api/runs/run-1/accept")
        discarded = await client.post("/api/runs/run-1/discard")

    assert rejected.status_code == 409
    assert discarded.status_code == 200
    assert discarded.json()["review_status"] == "discarded"


async def test_running_run_cannot_be_reviewed(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    record.status = "running"
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        accepted = await client.post("/api/runs/run-1/accept")
        discarded = await client.post("/api/runs/run-1/discard")

    assert accepted.status_code == 409
    assert discarded.status_code == 409
    assert record.review_status == "pending"


class FailingWorkspaceService(WorkspaceService):
    def __init__(self) -> None:
        super().__init__()
        self.write_count = 0

    def _replace_file(self, source: Path, target: Path) -> None:
        self.write_count += 1
        if self.write_count == 2:
            raise OSError("simulated write failure")
        super()._replace_file(source, target)


async def test_accept_rolls_back_when_a_write_fails(tmp_path, monkeypatch) -> None:
    manager, record = prepare_repository(tmp_path)
    manager.workspace_service = FailingWorkspaceService()
    monkeypatch.setattr(main_module, "repository_root", tmp_path)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/runs/run-1/accept")

    project = tmp_path / "examples" / "todo-demo"
    assert response.status_code == 503
    assert "已回滚" in response.json()["detail"]
    assert record.review_status == "pending"
    assert (project / "source.js").read_text(encoding="utf-8") == "const value = 'before';\n"
    assert not (project / "added.txt").exists()
    assert (project / "README.md").is_file()
