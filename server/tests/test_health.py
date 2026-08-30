from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import app
from app.projects import ProjectRegistry


async def request(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def test_health_endpoint() -> None:
    response = await request("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "intentflow-server",
        "version": "0.1.0",
    }


async def test_project_endpoint_returns_the_active_registered_project(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "my-project"
    root.mkdir()
    registry = ProjectRegistry(tmp_path / "intentflow.db", tmp_path)
    expected = registry.register(root)
    monkeypatch.setattr(main_module, "project_registry", registry)

    response = await request("/api/project")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == expected.id
    assert payload["name"] == "my-project"
    assert payload["root_path"] == str(root)
    assert payload["ready"] is True
