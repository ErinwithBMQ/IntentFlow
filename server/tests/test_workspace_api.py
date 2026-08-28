import shutil
from pathlib import Path

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.runs import RunManager, RunRecord


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
    assert changes.json()["changed_files"] == 2
    assert [item["path"] for item in changes.json()["files"]] == [
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
