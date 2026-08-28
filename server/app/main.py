from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.models import IntentBrief
from app.intent import (
    AIIntentCompiler,
    CanvasCompileRequest,
    CanvasCompileResponse,
    IntentCompileError,
    compile_canvas,
    validate_canvas_input,
)
from app.runs import RunManager, RunSnapshot


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
repository_root = Path(__file__).resolve().parents[2]
run_manager = RunManager(repository_root)


class CreateRunRequest(BaseModel):
    intent: IntentBrief


@app.get("/api/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/project", response_model=ProjectResponse)
async def get_project() -> ProjectResponse:
    project_path = repository_root / "examples" / "todo-demo"
    return ProjectResponse(
        name="todo-demo",
        relativePath="examples/todo-demo",
        ready=project_path.is_dir(),
    )


@app.post("/api/intent/compile", response_model=CanvasCompileResponse)
async def compile_intent(request: CanvasCompileRequest) -> CanvasCompileResponse:
    try:
        validate_canvas_input(request.canvas)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if request.compiler == "local":
        try:
            brief = compile_canvas(request.canvas)
        except (IntentCompileError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return CanvasCompileResponse(
            brief=brief,
            compiler="local",
            notice="AI 整理未使用；当前结果来自用户主动选择的本地规则降级。",
        )

    try:
        compiler = create_ai_intent_compiler()
        brief = await compiler.compile(request.canvas)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except IntentCompileError as error:
        raise HTTPException(status_code=502, detail=f"AI 意图整理失败：{error}") from error
    return CanvasCompileResponse(
        brief=brief,
        compiler="ai",
        notice="已使用真实模型整理，并通过需求编号和来源便签校验。",
    )


def create_ai_intent_compiler() -> AIIntentCompiler:
    config = dotenv_values(repository_root / ".env")
    api_key = (config.get("OPENAI_API_KEY") or "").strip()
    model = (config.get("OPENAI_MODEL") or "").strip()
    base_url = (config.get("OPENAI_BASE_URL") or "").strip() or None
    if not api_key or not model:
        raise ValueError("请先在根目录 .env 配置 OPENAI_API_KEY 和 OPENAI_MODEL")
    return AIIntentCompiler(
        model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=120.0,
    )


@app.post("/api/runs", response_model=RunSnapshot, status_code=201)
async def create_run(request: CreateRunRequest) -> RunSnapshot:
    try:
        return run_manager.start(request.intent)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/runs/{run_id}", response_model=RunSnapshot)
async def get_run(run_id: str) -> RunSnapshot:
    record = run_manager.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return record.snapshot()


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str) -> StreamingResponse:
    if run_manager.get(run_id) is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return StreamingResponse(
        run_manager.stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/stop", response_model=RunSnapshot)
async def stop_run(run_id: str) -> RunSnapshot:
    try:
        return await run_manager.stop(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="运行记录不存在") from error
