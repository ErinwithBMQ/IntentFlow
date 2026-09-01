import asyncio
import json
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.projects import ProjectRegistrationError, ProjectRegistry
from app.runs import RunManager, RunSnapshot
from app.sessions import ProjectRecord, SessionStore


def test_registry_registers_deduplicates_and_activates_projects(tmp_path: Path) -> None:
    database = tmp_path / "runtime-data" / "intentflow.db"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    registry = ProjectRegistry(database, tmp_path)

    first = registry.register(first_root)
    duplicate = registry.register(first_root / ".")
    second = registry.register(second_root)

    assert duplicate.id == first.id
    assert registry.get_active() == second
    assert [project.id for project in registry.list()] == [second.id, first.id]
    assert registry.activate(first.id).id == first.id
    assert registry.get_active() is not None
    assert registry.get_active().id == first.id


def test_registry_rejects_missing_files_and_runtime_data(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-data"
    checkpoint = runtime_root / "runs" / "run-1" / "checkpoint"
    checkpoint.mkdir(parents=True)
    registry = ProjectRegistry(runtime_root / "intentflow.db", tmp_path)

    with pytest.raises(ProjectRegistrationError, match="不存在"):
        registry.register(tmp_path / "missing")
    with pytest.raises(ProjectRegistrationError, match="运行数据目录"):
        registry.register(checkpoint)


def test_registry_migrates_the_legacy_relative_project(tmp_path: Path) -> None:
    project_root = tmp_path / "examples" / "todo-demo"
    project_root.mkdir(parents=True)
    database = tmp_path / "runtime-data" / "intentflow.db"
    store = SessionStore(database)
    store.ensure_project(
        ProjectRecord(
            id="todo-demo",
            name="todo-demo",
            relative_path="examples/todo-demo",
        )
    )

    registry = ProjectRegistry(database, tmp_path)
    migrated = registry.get("todo-demo")

    assert migrated is not None
    assert Path(migrated.root_path) == project_root
    assert migrated.relative_path == "examples/todo-demo"
    assert migrated.prompt == ""


def test_registry_creates_a_dependency_free_web_template(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "runtime-data" / "intentflow.db", tmp_path)

    project = registry.create(tmp_path, "hello-web", "web")
    root = Path(project.root_path)
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"] == {"test": "node --test", "build": "node build.mjs"}
    assert project.test_command == ["npm", "test"]
    assert project.build_command == ["npm", "run", "build"]
    assert (root / "src" / "main.js").is_file()


def test_registry_updates_safe_command_and_ignore_configuration(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = ProjectRegistry(tmp_path / "runtime-data" / "intentflow.db", tmp_path)
    project = registry.register(project_root)

    updated = registry.update(
        project.id,
        name="Renamed",
        test_command=["python", "-m", "pytest"],
        build_command=None,
        ignored_names=["generated", "nested/path"],
        prompt="默认使用中文，并保持现有代码风格。",
    )

    assert updated.name == "Renamed"
    assert updated.test_command == ["python", "-m", "pytest"]
    assert updated.build_command is None
    assert "generated" in updated.ignored_names
    assert "nested/path" not in updated.ignored_names
    assert "node_modules" in updated.ignored_names
    assert updated.prompt == "默认使用中文，并保持现有代码风格。"
    assert ProjectRegistry(registry.database_path, tmp_path).get(project.id) == updated


async def test_project_api_registers_creates_and_switches_projects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "runtime-data" / "intentflow.db"
    store = SessionStore(database)
    registry = ProjectRegistry(database, tmp_path)
    manager = RunManager(tmp_path, project_resolver=registry.get)
    existing = tmp_path / "existing"
    parent = tmp_path / "created"
    existing.mkdir()
    parent.mkdir()
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "project_registry", registry)
    monkeypatch.setattr(main_module, "run_manager", manager)
    transport = ASGITransport(app=main_module.app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        empty = await client.get("/api/project")
        registered = await client.post("/api/projects", json={"path": str(existing)})
        created = await client.post(
            "/api/projects/create",
            json={"parent_path": str(parent), "name": "new-web", "template": "web"},
        )
        first_session = await client.post(
            "/api/sessions",
            json={"project_id": registered.json()["id"], "title": "First"},
        )
        second_session = await client.post(
            "/api/sessions",
            json={"project_id": created.json()["id"], "title": "Second"},
        )
        first_sessions = await client.get(
            "/api/sessions",
            params={"project_id": registered.json()["id"]},
        )
        switched = await client.post(
            f"/api/projects/{registered.json()['id']}/activate"
        )
        updated = await client.patch(
            f"/api/projects/{registered.json()['id']}",
            json={
                "name": "Existing",
                "test_command": None,
                "build_command": None,
                "ignored_names": [],
                "prompt": "所有回复使用中文。",
            },
        )
        projects = await client.get("/api/projects")

    assert empty.status_code == 200
    assert empty.json() is None
    assert registered.status_code == 201
    assert created.status_code == 201
    assert Path(created.json()["root_path"], "index.html").is_file()
    assert first_session.json()["project_id"] == registered.json()["id"]
    assert second_session.json()["project_id"] == created.json()["id"]
    assert [item["id"] for item in first_sessions.json()] == [first_session.json()["id"]]
    assert switched.status_code == 200
    assert switched.json()["id"] == registered.json()["id"]
    assert updated.status_code == 200
    assert updated.json()["prompt"] == "所有回复使用中文。"
    assert len(projects.json()) == 2


async def test_project_api_uses_native_picker_and_blocks_switch_during_message(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "runtime-data" / "intentflow.db"
    store = SessionStore(database)
    registry = ProjectRegistry(database, tmp_path)
    manager = RunManager(tmp_path, project_resolver=registry.get)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first = registry.register(first_root)
    second = registry.register(second_root)
    registry.activate(first.id)
    monkeypatch.setattr(main_module, "session_store", store)
    monkeypatch.setattr(main_module, "project_registry", registry)
    monkeypatch.setattr(main_module, "run_manager", manager)
    monkeypatch.setattr(main_module, "choose_directory", lambda: str(second_root))
    blocker = asyncio.create_task(asyncio.Event().wait())
    main_module.active_message_tasks["session-busy"] = blocker
    transport = ASGITransport(app=main_module.app)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            blocked = await client.post(f"/api/projects/{second.id}/activate")
            main_module.active_message_tasks.clear()
            picked = await client.post("/api/projects/pick-directory")
    finally:
        main_module.active_message_tasks.clear()
        blocker.cancel()
        await asyncio.gather(blocker, return_exceptions=True)

    assert blocked.status_code == 409
    assert picked.status_code == 200
    assert picked.json()["id"] == second.id


def test_restored_run_applies_only_to_its_registered_project(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "value.txt").write_text("first", encoding="utf-8")
    (second_root / "value.txt").write_text("second", encoding="utf-8")
    registry = ProjectRegistry(tmp_path / "runtime-data" / "intentflow.db", tmp_path)
    registry.register(first_root)
    second = registry.register(second_root)
    run_root = tmp_path / "runtime-data" / "runs" / "run-second"
    baseline = run_root / "baseline" / "workspace"
    workspace = run_root / "workspace"
    shutil.copytree(second_root, baseline)
    shutil.copytree(baseline, workspace)
    (workspace / "value.txt").write_text("changed", encoding="utf-8")
    manager = RunManager(tmp_path, project_resolver=registry.get)
    manager.restore(
        RunSnapshot(
            id="run-second",
            status="completed",
            review_status="pending",
            workspace_relative_path="runtime-data/runs/run-second/workspace",
            project_id=second.id,
            project_name=second.name,
            events=[],
        )
    )

    manager.accept("run-second")

    assert (first_root / "value.txt").read_text(encoding="utf-8") == "first"
    assert (second_root / "value.txt").read_text(encoding="utf-8") == "changed"


def test_run_copy_ignores_symbolic_links_that_leave_the_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    link = project_root / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")

    ignored = RunManager._copy_ignore(frozenset())(str(project_root), ["external"])

    assert ignored == ["external"]
