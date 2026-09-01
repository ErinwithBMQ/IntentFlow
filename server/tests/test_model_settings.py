from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import app
from app.model_settings import ModelSettingsStore


async def request(method: str, path: str, *, json: dict | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=json)


async def test_model_settings_api_keeps_key_private_and_switches_model(
    tmp_path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=env-secret\n"
        "OPENAI_MODEL=env-model\n"
        "OPENAI_BASE_URL=https://env.example.com/v1\n",
        encoding="utf-8",
    )
    store = ModelSettingsStore(tmp_path / "intentflow.db", env_path)
    monkeypatch.setattr(main_module, "model_settings_store", store)

    initial = await request("GET", "/api/model-settings")
    assert initial.status_code == 200
    assert initial.json() == {
        "base_url": "https://env.example.com/v1",
        "models": ["env-model"],
        "active_model": "env-model",
        "has_api_key": True,
    }
    assert "env-secret" not in initial.text

    updated = await request(
        "PUT",
        "/api/model-settings",
        json={
            "api_key": "stored-secret",
            "base_url": "https://stored.example.com/v1/",
            "models": ["model-a", "model-b", "model-a"],
            "active_model": "model-a",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["models"] == ["model-a", "model-b"]
    assert updated.json()["base_url"] == "https://stored.example.com/v1"
    assert "stored-secret" not in updated.text

    selected = await request(
        "PATCH",
        "/api/model-settings/active",
        json={"model": "model-b"},
    )
    assert selected.status_code == 200
    assert selected.json()["active_model"] == "model-b"
    assert store.require_config() == (
        "stored-secret",
        "model-b",
        "https://stored.example.com/v1",
    )


async def test_model_settings_api_rejects_unknown_active_model(
    tmp_path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=secret\nOPENAI_MODEL=model-a\n", encoding="utf-8")
    store = ModelSettingsStore(tmp_path / "intentflow.db", env_path)
    monkeypatch.setattr(main_module, "model_settings_store", store)

    response = await request(
        "PATCH",
        "/api/model-settings/active",
        json={"model": "unknown-model"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "所选模型不在已配置列表中"
