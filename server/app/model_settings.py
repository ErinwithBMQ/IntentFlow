from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import BaseModel, Field

MODEL_API_KEY = "model_api_key"
MODEL_BASE_URL = "model_base_url"
MODEL_LIST = "model_list"
MODEL_ACTIVE = "model_active"
MAX_MODELS = 20


class ModelSettings(BaseModel):
    base_url: str = ""
    models: list[str] = Field(default_factory=list)
    active_model: str = ""
    has_api_key: bool = False


class ModelSettingsError(ValueError):
    """Raised when the shared model configuration is invalid or incomplete."""


class ModelSettingsStore:
    def __init__(self, database_path: Path, env_path: Path) -> None:
        self.database_path = database_path
        self.env_path = env_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def get(self) -> ModelSettings:
        values = self._stored_values()
        environment = dotenv_values(self.env_path)
        api_key = values.get(MODEL_API_KEY, "") or str(
            environment.get("OPENAI_API_KEY") or ""
        ).strip()
        base_url = (
            values[MODEL_BASE_URL]
            if MODEL_BASE_URL in values
            else str(environment.get("OPENAI_BASE_URL") or "").strip()
        )
        models = self._stored_models(values.get(MODEL_LIST))
        if not models:
            environment_model = str(environment.get("OPENAI_MODEL") or "").strip()
            models = [environment_model] if environment_model else []
        configured_active = values.get(MODEL_ACTIVE, "").strip()
        active_model = configured_active if configured_active in models else (
            models[0] if models else ""
        )
        return ModelSettings(
            base_url=base_url,
            models=models,
            active_model=active_model,
            has_api_key=bool(api_key),
        )

    def update(
        self,
        *,
        api_key: str | None,
        base_url: str,
        models: list[str],
        active_model: str,
    ) -> ModelSettings:
        clean_models = _validate_models(models)
        clean_active = active_model.strip()
        if clean_active not in clean_models:
            raise ModelSettingsError("当前模型必须包含在模型列表中")
        clean_base_url = _validate_base_url(base_url)
        clean_api_key = api_key.strip() if api_key is not None else None
        if clean_api_key is not None and len(clean_api_key) > 4_096:
            raise ModelSettingsError("API Key 不能超过 4096 个字符")

        current = self.get()
        if not clean_api_key and not current.has_api_key:
            raise ModelSettingsError("请填写 API Key")

        values = {
            MODEL_BASE_URL: clean_base_url,
            MODEL_LIST: json.dumps(clean_models, ensure_ascii=False),
            MODEL_ACTIVE: clean_active,
        }
        if clean_api_key:
            values[MODEL_API_KEY] = clean_api_key
        self._write_values(values)
        return self.get()

    def set_active_model(self, model: str) -> ModelSettings:
        settings = self.get()
        clean_model = model.strip()
        if clean_model not in settings.models:
            raise ModelSettingsError("所选模型不在已配置列表中")
        self._write_values({MODEL_ACTIVE: clean_model})
        return self.get()

    def require_config(self) -> tuple[str, str, str | None]:
        values = self._stored_values()
        environment = dotenv_values(self.env_path)
        api_key = values.get(MODEL_API_KEY, "") or str(
            environment.get("OPENAI_API_KEY") or ""
        ).strip()
        settings = self.get()
        if not api_key or not settings.active_model:
            raise ModelSettingsError("请先在顶部模型配置中填写 API Key 并选择模型")
        return api_key, settings.active_model, settings.base_url or None

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                )
                """
            )

    def _stored_values(self) -> dict[str, str]:
        keys = (MODEL_API_KEY, MODEL_BASE_URL, MODEL_LIST, MODEL_ACTIVE)
        placeholders = ", ".join("?" for _ in keys)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def _write_values(self, values: dict[str, str]) -> None:
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                values.items(),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _stored_models(payload: str | None) -> list[str]:
        if not payload:
            return []
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return []
        return _unique_models(value)


def _validate_models(models: list[str]) -> list[str]:
    clean = _unique_models(models)
    if not clean:
        raise ModelSettingsError("请至少配置一个模型")
    if len(clean) > MAX_MODELS or any(len(model) > 200 for model in clean):
        raise ModelSettingsError("模型配置过长")
    return clean


def _unique_models(models: list[str]) -> list[str]:
    return list(dict.fromkeys(model.strip() for model in models if model.strip()))


def _validate_base_url(base_url: str) -> str:
    clean = base_url.strip().rstrip("/")
    if not clean:
        return ""
    if len(clean) > 2_048:
        raise ModelSettingsError("API URL 不能超过 2048 个字符")
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelSettingsError("API URL 必须是有效的 http 或 https 地址")
    return clean
