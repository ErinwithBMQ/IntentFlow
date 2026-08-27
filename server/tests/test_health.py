from httpx import ASGITransport, AsyncClient

from app.main import app


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


async def test_project_endpoint_finds_the_demo() -> None:
    response = await request("/api/project")

    assert response.status_code == 200
    assert response.json() == {
        "name": "todo-demo",
        "relativePath": "examples/todo-demo",
        "ready": True,
    }
