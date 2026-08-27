from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "intentflow-server"
    version: str = "0.1.0"


class ProjectResponse(BaseModel):
    name: str
    relativePath: str
    ready: bool


app = FastAPI(
    title="IntentFlow API",
    version="0.1.0",
    description="Local API for the IntentFlow coding agent.",
)


@app.get("/api/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/project", response_model=ProjectResponse)
async def get_project() -> ProjectResponse:
    workspace_root = Path(__file__).resolve().parents[2]
    project_path = workspace_root / "examples" / "todo-demo"
    return ProjectResponse(
        name="todo-demo",
        relativePath="examples/todo-demo",
        ready=project_path.is_dir(),
    )

