from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.models import IntentBrief
from app.conversation_service import (
    ConversationResponder,
    ConversationResponseError,
    build_project_context,
)
from app.intent import (
    AIIntentCompiler,
    CanvasCompileRequest,
    CanvasCompileResponse,
    IntentCompileError,
    compile_canvas,
    validate_canvas_input,
)
from app.intent.models import CanvasNote, CanvasPosition, IntentCanvas
from app.runs import RunManager, RunRecord, RunReviewError, RunSnapshot
from app.sessions import (
    ConversationMessage,
    ConversationMode,
    ProjectRecord,
    SessionDetail,
    SessionRecord,
    SessionStore,
)
from app.workspaces import (
    ChangeSummary,
    FileDiff,
    WorkspaceAccessError,
    WorkspaceApplyError,
    WorkspaceConflictError,
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
project_record = ProjectRecord(
    id="todo-demo",
    name="todo-demo",
    relative_path="examples/todo-demo",
)
session_store = SessionStore(repository_root / "runtime-data" / "intentflow.db")
session_store.ensure_project(project_record)
run_manager = RunManager(repository_root, snapshot_sink=session_store.save_run)
for stored_run in session_store.load_runs():
    run_manager.restore(stored_run)
workspace_service = WorkspaceService()


class CreateRunRequest(BaseModel):
    intent: IntentBrief


class CreateSessionRequest(BaseModel):
    title: str = "新对话"


class SendSessionMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: ConversationMode = "agent"
    attach_canvas: bool = False
    canvas: IntentCanvas | None = None


class SendSessionMessageResponse(BaseModel):
    user_message: ConversationMessage
    assistant_message: ConversationMessage
    run: RunSnapshot | None = None


class ResolveApprovalRequest(BaseModel):
    decision: Literal["allow_once", "allow_for_run", "reject"]


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


@app.get("/api/sessions", response_model=list[SessionRecord])
async def list_sessions() -> list[SessionRecord]:
    return session_store.list_sessions(project_record.id)


@app.post("/api/sessions", response_model=SessionRecord, status_code=201)
async def create_session(request: CreateSessionRequest) -> SessionRecord:
    return session_store.create_session(project_record.id, request.title)


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str) -> SessionDetail:
    detail = session_store.get_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return detail


@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> Response:
    detail = session_store.get_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    if any(run.status == "running" for run in detail.runs):
        raise HTTPException(status_code=409, detail="运行中的对话不能删除，请先停止 Agent")

    try:
        for run in detail.runs:
            run_manager.delete(run.id, run.workspace_relative_path)
    except (OSError, RunReviewError) as error:
        raise HTTPException(status_code=503, detail=f"删除运行副本失败：{error}") from error

    session_store.delete_session(session_id)
    return Response(status_code=204)


@app.post(
    "/api/sessions/{session_id}/messages",
    response_model=SendSessionMessageResponse,
    status_code=201,
)
async def send_session_message(
    session_id: str,
    request: SendSessionMessageRequest,
) -> SendSessionMessageResponse:
    if session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if request.attach_canvas and request.canvas is None:
        raise HTTPException(status_code=422, detail="选择附加 Canvas 时必须提供当前画布")
    if request.mode == "agent":
        pending_run = session_store.get_pending_review_run(session_id)
        if pending_run is not None:
            detail = (
                "上一轮 Agent 仍在运行，请等待运行结束后应用或放弃修改"
                if pending_run.status == "running"
                else "请先应用或放弃上一轮 Agent 修改，再开始下一轮"
            )
            raise HTTPException(status_code=409, detail=detail)

    canvas_snapshot = (
        session_store.add_canvas_snapshot(session_id, request.canvas)
        if request.attach_canvas and request.canvas is not None
        else None
    )
    user_message = session_store.add_message(
        session_id,
        "user",
        request.mode,
        content,
        canvas_snapshot_id=canvas_snapshot.id if canvas_snapshot else None,
    )
    history = session_store.get_detail(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    project_context = build_project_context(
        repository_root / Path(project_record.relative_path)
    )

    if request.mode == "ask":
        try:
            answer = await create_conversation_responder().answer(
                history.messages,
                canvas_snapshot.canvas if canvas_snapshot else None,
                project_context,
            )
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ConversationResponseError as error:
            raise HTTPException(status_code=502, detail=f"AI 回复失败：{error}") from error
        assistant_message = session_store.add_message(session_id, "assistant", "ask", answer)
        return SendSessionMessageResponse(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    compilation_canvas = conversation_canvas(
        user_message,
        canvas_snapshot.canvas if canvas_snapshot else None,
        history.messages[:-1],
    )
    try:
        compiler = create_ai_intent_compiler()
        if request.mode == "agent":
            decision = await compiler.compile_agent_request(
                compilation_canvas,
                user_message.id,
                project_context=project_context,
            )
            if decision.brief is None:
                assistant_message = session_store.add_message(
                    session_id,
                    "assistant",
                    "agent",
                    decision.response or "请告诉我希望修改或验证的具体内容。",
                )
                return SendSessionMessageResponse(
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            brief = decision.brief
        else:
            decision = await compiler.compile_plan_request(
                compilation_canvas,
                user_message.id,
                project_context=project_context,
            )
            if decision.brief is None:
                assistant_message = session_store.add_message(
                    session_id,
                    "assistant",
                    "plan",
                    decision.response or "请告诉我希望规划的具体改动。",
                )
                return SendSessionMessageResponse(
                    user_message=user_message,
                    assistant_message=assistant_message,
                )
            brief = decision.brief
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except IntentCompileError as error:
        raise HTTPException(status_code=502, detail=f"AI 意图整理失败：{error}") from error

    if request.mode == "plan":
        assistant_message = session_store.add_message(
            session_id,
            "assistant",
            "plan",
            f"我根据当前项目整理了《{brief.title}》计划。",
            intent=brief,
        )
        return SendSessionMessageResponse(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    try:
        run = run_manager.start(
            brief,
            session_id=session_id,
            trigger_message_id=user_message.id,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    session_store.attach_run(user_message.id, run.id)
    assistant_message = session_store.add_message(
        session_id,
        "assistant",
        "agent",
        f"已整理为《{brief.title}》，开始在隔离工作区执行。",
        run_id=run.id,
        intent=brief,
    )
    return SendSessionMessageResponse(
        user_message=user_message.model_copy(update={"run_id": run.id}),
        assistant_message=assistant_message,
        run=run,
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
    api_key, model, base_url = model_config()
    return AIIntentCompiler(
        model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=120.0,
    )


def create_conversation_responder() -> ConversationResponder:
    api_key, model, base_url = model_config()
    return ConversationResponder(
        model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=120.0,
    )


def model_config() -> tuple[str, str, str | None]:
    config = dotenv_values(repository_root / ".env")
    api_key = (config.get("OPENAI_API_KEY") or "").strip()
    model = (config.get("OPENAI_MODEL") or "").strip()
    base_url = (config.get("OPENAI_BASE_URL") or "").strip() or None
    if not api_key or not model:
        raise ValueError("请先在根目录 .env 配置 OPENAI_API_KEY 和 OPENAI_MODEL")
    return api_key, model, base_url


def conversation_canvas(
    message: ConversationMessage,
    attached_canvas: IntentCanvas | None,
    previous_messages: list[ConversationMessage],
) -> IntentCanvas:
    canvas = attached_canvas.model_copy(deep=True) if attached_canvas else IntentCanvas()
    canvas.notes.append(
        CanvasNote(
            id=message.id,
            text=message.content,
            label="idea",
            position=CanvasPosition(x=0, y=0),
        )
    )
    prior_context = [
        f"{item.role}: {item.content}"
        for item in previous_messages
        if item.content.strip()
    ]
    if prior_context:
        context_text = "此前对话（仅作为上下文）：\n" + "\n".join(prior_context)
        canvas.supplemental_text = "\n\n".join(
            part for part in [canvas.supplemental_text.strip(), context_text] if part
        )
    return canvas


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


@app.post(
    "/api/runs/{run_id}/approvals/{approval_id}",
    response_model=RunSnapshot,
)
async def resolve_run_approval(
    run_id: str,
    approval_id: str,
    request: ResolveApprovalRequest,
) -> RunSnapshot:
    try:
        return run_manager.resolve_approval(run_id, approval_id, request.decision)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="运行记录不存在") from error
    except RunReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/runs/{run_id}/accept", response_model=RunSnapshot)
async def accept_run(run_id: str) -> RunSnapshot:
    try:
        return run_manager.accept(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="运行记录不存在") from error
    except (RunReviewError, WorkspaceConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error
    except WorkspaceApplyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/runs/{run_id}/discard", response_model=RunSnapshot)
async def discard_run(run_id: str) -> RunSnapshot:
    try:
        return run_manager.discard(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="运行记录不存在") from error
    except RunReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
