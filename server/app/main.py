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
from app.runs import RunManager, RunRecord, RunSnapshot
from app.workspaces import (
    ChangeSummary,
    FileDiff,
    WorkspaceAccessError,
    WorkspaceFile,
    WorkspaceService,
    WorkspaceTree,
)


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
workspace_service = WorkspaceService()


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


@app.get("/api/project/tree", response_model=WorkspaceTree)
async def get_project_tree() -> WorkspaceTree:
    try:
        return workspace_service.tree(project_root(), "todo-demo")
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/project/file", response_model=WorkspaceFile)
async def get_project_file(path: str) -> WorkspaceFile:
    try:
        return workspace_service.read_text(project_root(), path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


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


@app.get("/api/runs/{run_id}/tree", response_model=WorkspaceTree)
async def get_run_tree(run_id: str) -> WorkspaceTree:
    record = require_run(run_id)
    try:
        return workspace_service.tree(record.workspace, "todo-demo")
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/file", response_model=WorkspaceFile)
async def get_run_file(run_id: str, path: str) -> WorkspaceFile:
    record = require_run(run_id)
    try:
        return workspace_service.read_text(record.workspace, path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/changes", response_model=ChangeSummary)
async def get_run_changes(run_id: str) -> ChangeSummary:
    record = require_finished_run(run_id)
    try:
        return workspace_service.changes(record.baseline, record.workspace)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/diff", response_model=FileDiff)
async def get_run_file_diff(run_id: str, path: str) -> FileDiff:
    record = require_finished_run(run_id)
    try:
        return workspace_service.file_diff(record.baseline, record.workspace, path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


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


def project_root() -> Path:
    return repository_root / "examples" / "todo-demo"


def require_run(run_id: str) -> RunRecord:
    record = run_manager.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return record


def require_finished_run(run_id: str) -> RunRecord:
    record = require_run(run_id)
    if record.status == "running":
        raise HTTPException(status_code=409, detail="运行结束后才能生成正式 Diff")
    return record


def workspace_http_error(error: WorkspaceAccessError) -> HTTPException:
    status_code = {
        "invalid_path": 400,
        "not_file": 400,
        "not_found": 404,
        "too_large": 413,
        "too_many_files": 413,
        "binary": 415,
        "invalid_utf8": 415,
    }[error.kind]
    return HTTPException(status_code=status_code, detail=str(error))
