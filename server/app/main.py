import asyncio
import mimetypes
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agent.models import IntentBrief
from app.checkpoints import CheckpointConflictError, CheckpointError
from app.conversation_service import (
    ConversationResponder,
    ConversationResponseError,
    build_conversation_history_text,
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
from app.projects import (
    ProjectRecord,
    ProjectRegistrationError,
    ProjectRegistry,
    ProjectTemplate,
    choose_directory,
)
from app.runs import RunManager, RunRecord, RunReviewError, RunSnapshot
from app.session_context import ApprovalMode, SessionContextBuilder
from app.sessions import (
    ConversationMessage,
    ConversationMode,
    SessionDetail,
    SessionRecord,
    SessionStore,
    TaskDraftSnapshot,
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


class ProjectResponse(ProjectRecord):
    ready: bool


app = FastAPI(
    title="IntentFlow API",
    version="0.1.0",
    description="Local API for the IntentFlow coding agent.",
)
repository_root = Path(__file__).resolve().parents[2]
PREVIEW_FILE_SUFFIXES = frozenset(
    {
        ".css",
        ".gif",
        ".htm",
        ".html",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".mjs",
        ".otf",
        ".png",
        ".svg",
        ".ttf",
        ".wasm",
        ".webp",
        ".woff",
        ".woff2",
    }
)
PREVIEW_MEDIA_TYPES = {
    ".mjs": "text/javascript",
}
database_path = repository_root / "runtime-data" / "intentflow.db"
session_store = SessionStore(database_path)
project_registry = ProjectRegistry(database_path, repository_root)
run_manager = RunManager(
    repository_root,
    snapshot_sink=session_store.save_run,
    project_resolver=project_registry.get,
)
for stored_run in session_store.load_runs():
    if stored_run.project_id is None and stored_run.session_id:
        stored_session = session_store.get_session(stored_run.session_id)
        if stored_session is not None:
            stored_run.project_id = stored_session.project_id
    run_manager.restore(stored_run)


class CreateRunRequest(BaseModel):
    intent: IntentBrief
    approval_mode: ApprovalMode = "ask"
    project_id: str | None = None


class CreateSessionRequest(BaseModel):
    title: str = "新对话"
    project_id: str | None = None


class RegisterProjectRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4_096)


class CreateProjectRequest(BaseModel):
    parent_path: str = Field(min_length=1, max_length=4_096)
    name: str = Field(min_length=1, max_length=120)
    template: ProjectTemplate = "empty"


class UpdateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    test_command: list[str] | None = None
    build_command: list[str] | None = None
    ignored_names: list[str] = Field(default_factory=list)


class SendSessionMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    mode: ConversationMode = "agent"
    approval_mode: ApprovalMode | None = None
    attach_canvas: bool = False
    canvas: IntentCanvas | None = None


class SendSessionMessageResponse(BaseModel):
    user_message: ConversationMessage
    assistant_message: ConversationMessage
    run: RunSnapshot | None = None
    task_draft: TaskDraftSnapshot | None = None


class CancelSessionActivityResponse(BaseModel):
    cancelled: bool
    kind: Literal["message", "run", "none"]


class RunPreviewResponse(BaseModel):
    available: bool
    url: str | None = None


class DirectorySelectionResponse(BaseModel):
    path: str | None = None


class UpdateProjectFileRequest(BaseModel):
    content: str = Field(max_length=1_000_000)
    expected_content: str = Field(max_length=1_000_000)
    run_id: str | None = None


class UpdateProjectFileResponse(BaseModel):
    file: WorkspaceFile
    run: RunSnapshot | None = None
    changes: ChangeSummary | None = None


class ResolveApprovalRequest(BaseModel):
    decision: Literal["allow_once", "allow_for_run", "reject"]


active_message_tasks: dict[str, asyncio.Task[SendSessionMessageResponse]] = {}


@app.get("/api/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/projects", response_model=list[ProjectResponse])
async def list_projects() -> list[ProjectResponse]:
    return [project_response(project) for project in project_registry.list()]


@app.get("/api/project", response_model=ProjectResponse | None)
async def get_project() -> ProjectResponse | None:
    project = project_registry.get_active()
    return project_response(project) if project is not None else None


@app.post("/api/projects", response_model=ProjectResponse, status_code=201)
async def register_project(request: RegisterProjectRequest) -> ProjectResponse:
    ensure_project_change_available()
    try:
        return project_response(project_registry.register(request.path))
    except ProjectRegistrationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/projects/pick-directory", response_model=ProjectResponse | None)
async def pick_project_directory() -> ProjectResponse | None:
    ensure_project_change_available()
    try:
        selected = await asyncio.to_thread(choose_directory)
        return project_response(project_registry.register(selected)) if selected else None
    except ProjectRegistrationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/projects/pick-parent", response_model=DirectorySelectionResponse)
async def pick_parent_directory() -> DirectorySelectionResponse:
    try:
        return DirectorySelectionResponse(path=await asyncio.to_thread(choose_directory))
    except ProjectRegistrationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/projects/create", response_model=ProjectResponse, status_code=201)
async def create_project(request: CreateProjectRequest) -> ProjectResponse:
    ensure_project_change_available()
    try:
        project = project_registry.create(request.parent_path, request.name, request.template)
        return project_response(project)
    except (OSError, ProjectRegistrationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/projects/{project_id}/activate", response_model=ProjectResponse)
async def activate_project(project_id: str) -> ProjectResponse:
    current = project_registry.get_active()
    if (
        (current is None or current.id != project_id)
        and has_active_work()
    ):
        raise HTTPException(status_code=409, detail="当前任务仍在处理中，结束后才能切换项目")
    try:
        return project_response(project_registry.activate(project_id))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="项目不存在") from error


@app.patch("/api/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: UpdateProjectRequest,
) -> ProjectResponse:
    try:
        project = project_registry.update(
            project_id,
            name=request.name,
            test_command=request.test_command,
            build_command=request.build_command,
            ignored_names=request.ignored_names,
        )
        return project_response(project)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="项目不存在") from error
    except ProjectRegistrationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/sessions", response_model=list[SessionRecord])
async def list_sessions(project_id: str | None = None) -> list[SessionRecord]:
    project = require_project(project_id)
    return session_store.list_sessions(project.id)


@app.post("/api/sessions", response_model=SessionRecord, status_code=201)
async def create_session(request: CreateSessionRequest) -> SessionRecord:
    project = require_project(request.project_id)
    return session_store.create_session(project.id, request.title)


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
    if session_id in active_message_tasks:
        raise HTTPException(status_code=409, detail="正在处理消息，请先中断后再删除对话")
    if any(run.status == "running" for run in detail.runs):
        raise HTTPException(status_code=409, detail="运行中的对话不能删除，请先停止 Agent")

    try:
        for run in detail.runs:
            record = run_manager.get(run.id)
            if (
                record is not None
                and record.workspace_mode == "direct"
                and record.review_status == "pending"
            ):
                run_manager.discard(run.id)
            run_manager.delete(run.id, run.workspace_relative_path)
    except CheckpointConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (OSError, RunReviewError) as error:
        raise HTTPException(status_code=503, detail=f"删除运行记录失败：{error}") from error

    session_store.delete_session(session_id)
    return Response(status_code=204)


async def _process_session_message(
    session_id: str,
    request: SendSessionMessageRequest,
) -> SendSessionMessageResponse:
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    project = require_project(session.project_id)
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="消息内容不能为空")
    if request.attach_canvas and request.canvas is None:
        raise HTTPException(status_code=422, detail="选择附加 Canvas 时必须提供当前画布")
    approval_mode = request.approval_mode or session.approval_mode
    if request.approval_mode is not None and request.approval_mode != session.approval_mode:
        session_store.set_approval_mode(session_id, request.approval_mode)

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
    session_context = SessionContextBuilder(session_store).build(
        session_id,
        user_message,
        permission_policy=approval_mode,
    ).to_prompt_text()
    project_context = build_project_context(
        Path(project.root_path),
        frozenset(project.ignored_names),
    )

    if request.mode == "ask":
        try:
            answer = await create_conversation_responder().answer(
                history.messages,
                canvas_snapshot.canvas if canvas_snapshot else None,
                project_context,
                session_context,
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
                session_context=session_context,
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
                session_context=session_context,
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

    if request.mode == "plan" or decision.action == "propose":
        task_draft = session_store.add_task_draft(
            session_id,
            user_message.id,
            brief,
            status="proposed",
            canvas=canvas_snapshot.canvas if canvas_snapshot else None,
        )
        assistant_message = session_store.add_message(
            session_id,
            "assistant",
            "plan",
            f"收到，我先根据当前项目整理了一份《{brief.title}》计划。",
            task_draft_id=task_draft.id,
            intent=brief,
        )
        return SendSessionMessageResponse(
            user_message=user_message,
            assistant_message=assistant_message,
            task_draft=task_draft,
        )

    pending_run = session_store.get_pending_review_run(session_id)
    if pending_run is not None:
        pending_detail = (
            "上一轮 Agent 仍在运行。你可以继续询问进展，但需要等待它结束并处理修改后，"
            "才能开始新的执行。"
            if pending_run.status == "running"
            else "上一轮 Agent 修改仍待审查。你可以继续询问结果，但需要先保留修改或撤销本轮，"
            "才能开始新的执行。"
        )
        assistant_message = session_store.add_message(
            session_id,
            "assistant",
            "agent",
            pending_detail,
        )
        return SendSessionMessageResponse(
            user_message=user_message,
            assistant_message=assistant_message,
        )

    task_draft = session_store.add_task_draft(
        session_id,
        user_message.id,
        brief,
        status="confirmed",
        canvas=canvas_snapshot.canvas if canvas_snapshot else None,
    )
    try:
        run = run_manager.start(
            brief,
            session_id=session_id,
            trigger_message_id=user_message.id,
            task_draft_id=task_draft.id,
            prior_context=session_context,
            approval_mode=approval_mode,
            project=project,
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
        (
            f"收到，我会处理《{brief.title}》。修改前会按当前权限请求批准，完成后可以查看 Diff。"
        ),
        task_draft_id=task_draft.id,
        run_id=run.id,
        intent=brief,
    )
    return SendSessionMessageResponse(
        user_message=user_message.model_copy(update={"run_id": run.id}),
        assistant_message=assistant_message,
        run=run,
        task_draft=task_draft,
    )


@app.post(
    "/api/sessions/{session_id}/messages",
    response_model=SendSessionMessageResponse,
    status_code=201,
)
async def send_session_message(
    session_id: str,
    request: SendSessionMessageRequest,
) -> SendSessionMessageResponse:
    existing_task = active_message_tasks.get(session_id)
    if existing_task is not None and not existing_task.done():
        raise HTTPException(status_code=409, detail="当前消息仍在处理中")

    task = asyncio.create_task(_process_session_message(session_id, request))
    active_message_tasks[session_id] = task
    try:
        return await task
    except asyncio.CancelledError:
        detail = session_store.get_detail(session_id)
        latest_user_message = next(
            (
                message
                for message in reversed(detail.messages if detail else [])
                if message.role == "user"
            ),
            None,
        )
        if latest_user_message is None:
            raise HTTPException(status_code=409, detail="消息处理已中断") from None
        assistant_message = session_store.add_message(
            session_id,
            "assistant",
            latest_user_message.mode,
            "已中断本次处理，没有启动新的 Agent 运行。",
        )
        return SendSessionMessageResponse(
            user_message=latest_user_message,
            assistant_message=assistant_message,
        )
    finally:
        if active_message_tasks.get(session_id) is task:
            active_message_tasks.pop(session_id, None)


@app.post(
    "/api/sessions/{session_id}/cancel",
    response_model=CancelSessionActivityResponse,
)
async def cancel_session_activity(session_id: str) -> CancelSessionActivityResponse:
    if session_store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")

    message_task = active_message_tasks.get(session_id)
    if message_task is not None and not message_task.done():
        message_task.cancel()
        return CancelSessionActivityResponse(cancelled=True, kind="message")

    detail = session_store.get_detail(session_id)
    running_run = next(
        (run for run in reversed(detail.runs if detail else []) if run.status == "running"),
        None,
    )
    if running_run is not None:
        try:
            await run_manager.stop(running_run.id)
            record = run_manager.get(running_run.id)
            if record is not None and record.task is not None:
                await record.task
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行记录不存在") from error
        return CancelSessionActivityResponse(cancelled=True, kind="run")

    return CancelSessionActivityResponse(cancelled=False, kind="none")


@app.get("/api/project/tree", response_model=WorkspaceTree)
async def get_project_tree(project_id: str | None = None) -> WorkspaceTree:
    project = require_project(project_id)
    try:
        return project_workspace_service(project).tree(Path(project.root_path), project.name)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/project/file", response_model=WorkspaceFile)
async def get_project_file(path: str, project_id: str | None = None) -> WorkspaceFile:
    project = require_project(project_id)
    try:
        return project_workspace_service(project).read_text(Path(project.root_path), path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.put("/api/project/file", response_model=UpdateProjectFileResponse)
async def update_project_file(
    path: str,
    request: UpdateProjectFileRequest,
    project_id: str | None = None,
) -> UpdateProjectFileResponse:
    project = require_project(project_id)
    pending_runs = run_manager.pending_review_runs(project.id)
    if request.run_id is None:
        if pending_runs:
            raise HTTPException(
                status_code=409,
                detail="当前项目存在待审查的 Agent 修改，请将手动编辑并入该轮 Run",
            )
        try:
            updated = project_workspace_service(project).update_text(
                Path(project.root_path),
                path,
                request.content,
                request.expected_content,
            )
        except WorkspaceAccessError as error:
            raise workspace_http_error(error) from error
        return UpdateProjectFileResponse(file=updated)

    try:
        record = require_run(request.run_id)
        if record.project_id != project.id:
            raise HTTPException(status_code=409, detail="运行记录不属于当前项目")
        other_pending = [item for item in pending_runs if item.id != record.id]
        if other_pending:
            raise HTTPException(
                status_code=409,
                detail="当前项目存在其他待审查运行，暂不能手动保存",
            )
        snapshot, updated = await run_manager.apply_manual_edit(
            record.id,
            path,
            request.content,
            request.expected_content,
        )
        changes = (
            record.checkpoint.changes(run_workspace_service(record))
            if record.checkpoint
            else None
        )
        return UpdateProjectFileResponse(file=updated, run=snapshot, changes=changes)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="运行记录不存在") from error
    except (RunReviewError, CheckpointConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CheckpointError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
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
    prior_context = build_conversation_history_text(previous_messages)
    if prior_context:
        context_text = "此前对话（仅作为上下文）：\n" + prior_context
        canvas.supplemental_text = "\n\n".join(
            part for part in [canvas.supplemental_text.strip(), context_text] if part
        )
    return canvas


@app.post("/api/runs", response_model=RunSnapshot, status_code=201)
async def create_run(request: CreateRunRequest) -> RunSnapshot:
    project = (
        None
        if request.project_id is None and run_manager.default_project_root is not None
        else require_project(request.project_id)
    )
    try:
        return run_manager.start(
            request.intent,
            approval_mode=request.approval_mode,
            project=project,
        )
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
        return run_workspace_service(record).tree(record.workspace, record.project_name)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/file", response_model=WorkspaceFile)
async def get_run_file(run_id: str, path: str) -> WorkspaceFile:
    record = require_run(run_id)
    try:
        return run_workspace_service(record).read_text(record.workspace, path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/changes", response_model=ChangeSummary)
async def get_run_changes(run_id: str) -> ChangeSummary:
    record = require_finished_run(run_id)
    try:
        if record.workspace_mode == "direct" and record.checkpoint is not None:
            return record.checkpoint.changes(run_workspace_service(record))
        return run_workspace_service(record).changes(record.baseline, record.workspace)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/diff", response_model=FileDiff)
async def get_run_file_diff(run_id: str, path: str) -> FileDiff:
    record = require_finished_run(run_id)
    try:
        if record.workspace_mode == "direct" and record.checkpoint is not None:
            return record.checkpoint.file_diff(run_workspace_service(record), path)
        return run_workspace_service(record).file_diff(record.baseline, record.workspace, path)
    except WorkspaceAccessError as error:
        raise workspace_http_error(error) from error


@app.get("/api/runs/{run_id}/preview", response_model=RunPreviewResponse)
async def get_run_preview(run_id: str) -> RunPreviewResponse:
    record = require_run(run_id)
    preview_root = run_preview_root(record)
    return RunPreviewResponse(
        available=preview_root is not None,
        url=f"/api/runs/{run_id}/preview-files/" if preview_root is not None else None,
    )


@app.get("/api/runs/{run_id}/preview-files/{asset_path:path}")
async def get_run_preview_file(run_id: str, asset_path: str = "") -> Response:
    record = require_run(run_id)
    preview_root = run_preview_root(record)
    if preview_root is None:
        raise HTTPException(status_code=404, detail="当前运行没有可预览的网页入口")
    requested = asset_path or "index.html"
    target = (preview_root / requested).resolve()
    try:
        target.relative_to(preview_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="预览文件路径越过允许目录") from error
    if not target.is_file() or target.suffix.casefold() not in PREVIEW_FILE_SUFFIXES:
        raise HTTPException(status_code=404, detail="预览文件不存在")
    media_type = PREVIEW_MEDIA_TYPES.get(target.suffix.casefold())
    if media_type is None:
        media_type, _ = mimetypes.guess_type(target.name)
    if target.suffix.casefold() in {".html", ".htm"}:
        prefix = f"/api/runs/{run_id}/preview-files/"
        try:
            html = target.read_text(encoding="utf-8")
        except UnicodeError as error:
            raise HTTPException(status_code=415, detail="预览 HTML 不是 UTF-8 编码") from error
        html = html.replace('src="/', f'src="{prefix}').replace(
            'href="/', f'href="{prefix}'
        )
        return Response(
            content=html,
            media_type="text/html",
            headers={"Access-Control-Allow-Origin": "*"},
        )
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def run_preview_root(record: RunRecord) -> Path | None:
    for candidate in (record.workspace / "dist", record.workspace):
        resolved = candidate.resolve()
        if (resolved / "index.html").is_file():
            return resolved
    return None


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
    except (RunReviewError, CheckpointConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/runs/{run_id}/keep", response_model=RunSnapshot)
async def keep_run(run_id: str) -> RunSnapshot:
    return await accept_run(run_id)


@app.post("/api/runs/{run_id}/undo", response_model=RunSnapshot)
async def undo_run(run_id: str) -> RunSnapshot:
    return await discard_run(run_id)


def require_project(project_id: str | None = None) -> ProjectRecord:
    project = project_registry.get(project_id) if project_id else project_registry.get_active()
    if project is None:
        raise HTTPException(status_code=404, detail="请先选择或添加一个项目文件夹")
    try:
        project_registry.require_root(project.id)
    except ProjectRegistrationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return project


def has_active_work() -> bool:
    has_active_message = any(not task.done() for task in active_message_tasks.values())
    return has_active_message or run_manager.has_running()


def ensure_project_change_available() -> None:
    if has_active_work():
        raise HTTPException(status_code=409, detail="当前任务仍在处理中，结束后才能切换项目")


def project_response(project: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(**project.model_dump(), ready=Path(project.root_path).is_dir())


def project_workspace_service(project: ProjectRecord) -> WorkspaceService:
    return WorkspaceService(ignored_names=frozenset(project.ignored_names))


def run_workspace_service(record: RunRecord) -> WorkspaceService:
    return WorkspaceService(ignored_names=record.project_ignored_names)


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
        "conflict": 409,
        "not_file": 400,
        "not_found": 404,
        "too_large": 413,
        "too_many_files": 413,
        "binary": 415,
        "invalid_utf8": 415,
    }[error.kind]
    return HTTPException(status_code=status_code, detail=str(error))
