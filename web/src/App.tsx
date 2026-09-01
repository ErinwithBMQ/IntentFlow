import {
  Background,
  BackgroundVariant,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  CircleDot,
  FileCode2,
  GitCompareArrows,
  MessageSquarePlus,
  MonitorPlay,
  Plus,
  RotateCcw,
  Settings2,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DEFAULT_CANVAS_EDGES,
  DEFAULT_CANVAS_NODES,
  fromIntentCanvas,
  isStoredCanvas,
  toIntentCanvas,
  type NoteNode as NoteNodeType,
} from "./features/canvas/canvasState";
import { EditableEdge, EditableEdgeProvider } from "./features/canvas/EditableEdge";
import { NoteNode, NoteNodeProvider } from "./features/canvas/NoteNode";
import { ProjectDialog } from "./features/projects/ProjectDialog";
import { SingleRunConversation } from "./features/run/SingleRunConversation";
import { ConversationComposer } from "./features/session/ConversationComposer";
import { SessionConversation } from "./features/session/SessionConversation";
import { CodeWorkspace, type OpenWorkspaceFile } from "./features/workspace/CodeWorkspace";
import { DiffWorkspace } from "./features/workspace/DiffWorkspace";
import { ProjectExplorer } from "./features/workspace/ProjectExplorer";
import {
  relatedFileDestination,
  workspaceFileKey,
  type WorkspaceTab,
} from "./features/workspace/workspaceState";
import {
  activateProject,
  cancelSessionActivity,
  createProject,
  createSession,
  deleteSession,
  getHealth,
  getProject,
  getProjectFile,
  getProjectTree,
  getRun,
  getRunChanges,
  getRunFileDiff,
  getRunPreview,
  getSession,
  keepRun,
  listProjects,
  listSessions,
  pickParentDirectory,
  pickProjectDirectory,
  registerProject,
  resolveRunApproval,
  sendSessionMessage,
  subscribeToRun,
  updateProject,
  updateProjectFile,
  undoRun,
  type CanvasNoteLabel,
  type ChangeSummary,
  type ApprovalDecision,
  type ApprovalMode,
  type ConversationMessage,
  type FileChange,
  type FileDiff,
  type IntentBrief,
  type IntentCanvas,
  type ProjectResponse,
  type ProjectTemplate,
  type RunPreviewResponse,
  type RunSnapshot,
  type SessionRecord,
  type TaskDraftSnapshot,
  type WorkspaceTree,
} from "./services/api";

type ConnectionState = "checking" | "connected" | "failed";

const STORAGE_KEY = "intentflow.canvas.v1";
const CONVERSATION_WIDTH_KEY = "intentflow.conversation-width.v1";
const ACTIVE_SESSION_KEY = "intentflow.active-session.v1";
const MIN_CONVERSATION_WIDTH = 300;
const LEFT_PANEL_WIDTH = 240;
const MIN_MAIN_WORKSPACE_WIDTH = 80;
const nodeTypes = { note: NoteNode };
const edgeTypes = { default: EditableEdge };

function defaultCanvas() {
  return {
    nodes: DEFAULT_CANVAS_NODES.map((node) => ({ ...node, data: { ...node.data } })),
    edges: DEFAULT_CANVAS_EDGES.map((edge) => ({ ...edge })),
  };
}

function loadCanvas() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as unknown;
    if (isStoredCanvas(stored)) return stored;
  } catch {
    // Ignore invalid local data and restore the stable demo canvas.
  }
  return defaultCanvas();
}

function loadSessionCanvas(sessionId: string, fallbackCanvas: IntentCanvas | null) {
  const sessionStorageKey = `${STORAGE_KEY}.${sessionId}`;
  try {
    const stored = JSON.parse(localStorage.getItem(sessionStorageKey) ?? "null") as unknown;
    if (isStoredCanvas(stored)) return stored;
    const legacy = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as unknown;
    if (isStoredCanvas(legacy)) {
      localStorage.setItem(sessionStorageKey, JSON.stringify(legacy));
      localStorage.removeItem(STORAGE_KEY);
      return legacy;
    }
  } catch {
    // Ignore invalid local data and restore the latest persisted snapshot or the default canvas.
  }
  return fallbackCanvas ? fromIntentCanvas(fallbackCanvas) : defaultCanvas();
}

function clampConversationWidth(width: number): number {
  const maximumWidth = Math.max(
    MIN_CONVERSATION_WIDTH,
    window.innerWidth - LEFT_PANEL_WIDTH - MIN_MAIN_WORKSPACE_WIDTH,
  );
  return Math.min(maximumWidth, Math.max(MIN_CONVERSATION_WIDTH, width));
}

function loadConversationWidth(): number {
  const stored = Number(localStorage.getItem(CONVERSATION_WIDTH_KEY));
  return Number.isFinite(stored) && stored > 0 ? clampConversationWidth(stored) : 380;
}

export function App() {
  const initialCanvas = useMemo(loadCanvas, []);
  const [nodes, setNodes, onNodesChange] = useNodesState<NoteNodeType>(initialCanvas.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialCanvas.edges);
  const [canvasStorageSessionId, setCanvasStorageSessionId] = useState<string | null>(null);
  const [editingEdgeId, setEditingEdgeId] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [projectsReady, setProjectsReady] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [runBrief, setRunBrief] = useState<IntentBrief | null>(null);
  const [runError, setRunError] = useState("");
  const [reviewAction, setReviewAction] = useState<"keep" | "undo" | null>(null);
  const [toolApprovalAction, setToolApprovalAction] = useState<{
    approvalId: string;
    decision: ApprovalDecision;
  } | null>(null);
  const [reviewError, setReviewError] = useState("");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("canvas");
  const [projectTree, setProjectTree] = useState<WorkspaceTree | null>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [openFiles, setOpenFiles] = useState<OpenWorkspaceFile[]>([]);
  const [activeFileKey, setActiveFileKey] = useState<string | null>(null);
  const [changes, setChanges] = useState<ChangeSummary | null>(null);
  const [activeDiffPath, setActiveDiffPath] = useState<string | null>(null);
  const [activeDiff, setActiveDiff] = useState<FileDiff | null>(null);
  const [runPreview, setRunPreview] = useState<RunPreviewResponse | null>(null);
  const [previewRevision, setPreviewRevision] = useState(0);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState("");
  const [conversationWidth, setConversationWidth] = useState(loadConversationWidth);
  const [isResizingConversation, setIsResizingConversation] = useState(false);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionMessages, setSessionMessages] = useState<ConversationMessage[]>([]);
  const [sessionRuns, setSessionRuns] = useState<RunSnapshot[]>([]);
  const [taskDrafts, setTaskDrafts] = useState<TaskDraftSnapshot[]>([]);
  const [canvasProposal, setCanvasProposal] = useState<TaskDraftSnapshot | null>(null);
  const [adoptedTaskDraft, setAdoptedTaskDraft] = useState<TaskDraftSnapshot | null>(null);
  const [messageDraft, setMessageDraft] = useState("");
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>("ask");
  const [attachCanvas, setAttachCanvas] = useState(false);
  const [canvasPlanMode, setCanvasPlanMode] = useState(false);
  const [messageSending, setMessageSending] = useState(false);
  const [activityInterrupting, setActivityInterrupting] = useState(false);
  const [sessionDeleting, setSessionDeleting] = useState(false);
  const [messageError, setMessageError] = useState("");
  const closeRunStream = useRef<(() => void) | null>(null);
  const openFilesRef = useRef<OpenWorkspaceFile[]>([]);
  const diffRequestSequence = useRef(0);
  const workspaceTabRef = useRef<WorkspaceTab>("canvas");
  const activeDiffPathRef = useRef<string | null>(null);
  const autosaveTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(() => () => {
    autosaveTimers.current.forEach((timer) => clearTimeout(timer));
    autosaveTimers.current.clear();
  }, []);

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [health, projectInfo, availableProjects] = await Promise.all([
          getHealth(),
          getProject(),
          listProjects(),
        ]);
        if (active && health.status === "ok") {
          setConnection("connected");
          setProjects(availableProjects);
          if (projectInfo?.ready) {
            await loadProjectIntoView(projectInfo);
          } else {
            setProject(projectInfo);
            setProjectDialogOpen(true);
          }
        }
      } catch (error) {
        if (active) {
          setConnection("failed");
          setWorkspaceError(errorMessage(error, "无法读取项目文件"));
        }
      } finally {
        if (active) setProjectsReady(true);
      }
    }
    void bootstrap();
    return () => {
      active = false;
    };
    // Initial bootstrap intentionally runs once; project changes use handleProjectSwitch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!canvasStorageSessionId) return;
    localStorage.setItem(
      `${STORAGE_KEY}.${canvasStorageSessionId}`,
      JSON.stringify({ nodes, edges }),
    );
  }, [canvasStorageSessionId, edges, nodes]);

  useEffect(() => {
    localStorage.setItem(CONVERSATION_WIDTH_KEY, String(conversationWidth));
  }, [conversationWidth]);

  useEffect(() => {
    function handleWindowResize() {
      setConversationWidth((width) => clampConversationWidth(width));
    }

    window.addEventListener("resize", handleWindowResize);
    return () => window.removeEventListener("resize", handleWindowResize);
  }, []);

  useEffect(() => {
    if (!isResizingConversation) return;

    function handlePointerMove(event: PointerEvent) {
      setConversationWidth(clampConversationWidth(window.innerWidth - event.clientX));
    }

    function handlePointerUp() {
      setIsResizingConversation(false);
    }

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [isResizingConversation]);

  useEffect(() => () => closeRunStream.current?.(), []);

  useEffect(() => {
    workspaceTabRef.current = workspaceTab;
    activeDiffPathRef.current = activeDiffPath;
  }, [activeDiffPath, workspaceTab]);

  useEffect(() => {
    openFilesRef.current = openFiles;
  }, [openFiles]);

  const updateNote = useCallback(
    (id: string, text: string, label: CanvasNoteLabel | null) => {
      setNodes((currentNodes) =>
        currentNodes.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, text, label } } : node,
        ),
      );
    },
    [setNodes],
  );

  const removeNote = useCallback(
    (id: string) => {
      setNodes((currentNodes) => currentNodes.filter((node) => node.id !== id));
      setEdges((currentEdges) =>
        currentEdges.filter((edge) => edge.source !== id && edge.target !== id),
      );
      setEditingEdgeId(null);
    },
    [setEdges, setNodes],
  );

  const callbacks = useMemo(
    () => ({ editable: canvasProposal === null, onChange: updateNote, onRemove: removeNote }),
    [canvasProposal, removeNote, updateNote],
  );

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((currentEdges) =>
        addEdge({ ...params, label: "" }, currentEdges),
      );
    },
    [setEdges],
  );

  const updateEdgeLabel = useCallback(
    (id: string, label: string) => {
      setEdges((currentEdges) => currentEdges.map((edge) => (
        edge.id === id ? { ...edge, label } : edge
      )));
    },
    [setEdges],
  );

  const removeEdge = useCallback(
    (id: string) => {
      setEdges((currentEdges) => currentEdges.filter((edge) => edge.id !== id));
      setEditingEdgeId(null);
    },
    [setEdges],
  );

  const edgeCallbacks = useMemo(
    () => ({
      editable: canvasProposal === null,
      editingEdgeId,
      onStartEditing: setEditingEdgeId,
      onChange: updateEdgeLabel,
      onRemove: removeEdge,
      onFinishEditing: () => setEditingEdgeId(null),
    }),
    [canvasProposal, editingEdgeId, removeEdge, updateEdgeLabel],
  );

  function handleCanvasKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (canvasProposal || event.key !== "Enter" || event.defaultPrevented) return;
    const target = event.target as HTMLElement;
    if (target.matches("input, textarea, select, button") || target.isContentEditable) return;
    const selectedEdge = edges.find((edge) => edge.selected);
    if (!selectedEdge) return;
    event.preventDefault();
    setEditingEdgeId(selectedEdge.id);
  }

  function addNote() {
    const offset = nodes.length * 24;
    setNodes((currentNodes) => [
      ...currentNodes,
      {
        id: `note-${crypto.randomUUID()}`,
        type: "note",
        position: { x: 180 + (offset % 260), y: 140 + (offset % 220) },
        data: { text: "", label: null },
      },
    ]);
  }

  function restoreExample() {
    setNodes(DEFAULT_CANVAS_NODES.map((node) => ({ ...node, data: { ...node.data } })));
    setEdges(DEFAULT_CANVAS_EDGES.map((edge) => ({ ...edge })));
    setEditingEdgeId(null);
    setAdoptedTaskDraft(null);
  }

  function clearCanvas() {
    if (
      (nodes.length > 0 || edges.length > 0)
      && !window.confirm("清空当前对话的 Canvas 吗？便签和连线都会被删除。")
    ) return;
    setNodes([]);
    setEdges([]);
    setEditingEdgeId(null);
    setAdoptedTaskDraft(null);
  }

  function previewTaskDraft(draft: TaskDraftSnapshot) {
    if (!draft.canvas) return;
    setEditingEdgeId(null);
    setCanvasProposal(draft);
    setWorkspaceTab("canvas");
  }

  function adoptCanvasProposal() {
    if (!canvasProposal?.canvas) return;
    const confirmed = window.confirm(
      `采用任务草案 v${canvasProposal.version} 并替换当前 Canvas 吗？`,
    );
    if (!confirmed) return;
    const proposal = fromIntentCanvas(canvasProposal.canvas);
    setNodes(proposal.nodes);
    setEdges(proposal.edges);
    setEditingEdgeId(null);
    setAdoptedTaskDraft(canvasProposal);
    setCanvasProposal(null);
  }

  function clearRunReview() {
    diffRequestSequence.current += 1;
    activeDiffPathRef.current = null;
    setChanges(null);
    setActiveDiffPath(null);
    setActiveDiff(null);
    setRunPreview(null);
    setDiffError("");
    setDiffLoading(false);
    setReviewAction(null);
    setReviewError("");
  }

  async function loadProjectIntoView(selectedProject: ProjectResponse) {
    closeRunStream.current?.();
    autosaveTimers.current.forEach((timer) => clearTimeout(timer));
    autosaveTimers.current.clear();
    setProject(selectedProject);
    setProjectTree(null);
    setOpenFiles([]);
    setActiveFileKey(null);
    setSessionMessages([]);
    setSessionRuns([]);
    setTaskDrafts([]);
    setCanvasProposal(null);
    setAdoptedTaskDraft(null);
    setCanvasStorageSessionId(null);
    setRun(null);
    setRunBrief(null);
    clearRunReview();
    setWorkspaceError("");
    setMessageError("");

    try {
      const [tree, availableSessions] = await Promise.all([
        getProjectTree(selectedProject.id),
        listSessions(selectedProject.id),
      ]);
      setProjectTree(tree);
      const sessionStorageKey = `${ACTIVE_SESSION_KEY}.${selectedProject.id}`;
      const storedSessionId = localStorage.getItem(sessionStorageKey);
      let selectedSession = availableSessions.find(
        (session) => session.id === storedSessionId,
      ) ?? availableSessions[0];
      if (!selectedSession) {
        selectedSession = await createSession(selectedProject.id);
        availableSessions.unshift(selectedSession);
      }
      setSessions(availableSessions);
      await loadSessionIntoView(selectedSession.id, selectedProject.id);
    } catch (error) {
      setWorkspaceError(errorMessage(error, "无法打开项目"));
    }
  }

  async function adoptProject(selectedProject: ProjectResponse) {
    setProjectBusy(true);
    setProjectError("");
    try {
      setProjects(await listProjects());
      await loadProjectIntoView(selectedProject);
      setProjectDialogOpen(false);
    } catch (error) {
      setProjectError(errorMessage(error, "无法打开项目"));
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleProjectSwitch(projectId: string) {
    if (!project || project.id === projectId || projectBusy) return;
    if (
      openFiles.some((file) => file.file && file.draft !== file.file.content)
      && !window.confirm("仍有未保存的代码修改，切换项目会丢弃这些内容。继续吗？")
    ) return;
    setProjectBusy(true);
    setProjectError("");
    try {
      const activated = await activateProject(projectId);
      await loadProjectIntoView(activated);
      setProjects(await listProjects());
    } catch (error) {
      setProjectError(errorMessage(error, "无法切换项目"));
      setProjectDialogOpen(true);
    } finally {
      setProjectBusy(false);
    }
  }

  async function handlePickProject() {
    setProjectBusy(true);
    setProjectError("");
    try {
      const selected = await pickProjectDirectory();
      if (selected) await adoptProject(selected);
    } catch (error) {
      setProjectError(errorMessage(error, "无法打开文件夹选择器"));
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleRegisterProject(path: string) {
    setProjectBusy(true);
    setProjectError("");
    try {
      await adoptProject(await registerProject(path));
    } catch (error) {
      setProjectError(errorMessage(error, "无法添加项目"));
    } finally {
      setProjectBusy(false);
    }
  }

  async function handlePickParent(): Promise<string | null> {
    setProjectBusy(true);
    setProjectError("");
    try {
      return (await pickParentDirectory()).path;
    } catch (error) {
      setProjectError(errorMessage(error, "无法打开文件夹选择器"));
      return null;
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleCreateProject(
    parentPath: string,
    name: string,
    template: ProjectTemplate,
  ) {
    setProjectBusy(true);
    setProjectError("");
    try {
      await adoptProject(await createProject(parentPath, name, template));
    } catch (error) {
      setProjectError(errorMessage(error, "无法创建项目"));
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleSaveProject(updatedProject: ProjectResponse) {
    setProjectBusy(true);
    setProjectError("");
    try {
      const saved = await updateProject(updatedProject.id, updatedProject);
      setProject(saved);
      setProjects((current) => current.map((item) => item.id === saved.id ? saved : item));
      setProjectDialogOpen(false);
      setProjectTree(await getProjectTree(saved.id));
    } catch (error) {
      setProjectError(errorMessage(error, "无法保存项目设置"));
    } finally {
      setProjectBusy(false);
    }
  }

  async function refreshRun(runId: string) {
    try {
      const snapshot = await getRun(runId);
      setRun(snapshot);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === snapshot.id ? snapshot : item,
      ));
      await loadRunFacts(snapshot);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "无法读取运行结果");
    }
  }

  async function loadRunFacts(snapshot: RunSnapshot) {
    setWorkspaceError("");
    if (project) {
      try {
        setProjectTree(await getProjectTree(project.id));
        await refreshOpenProjectFiles();
      } catch (error) {
        setWorkspaceError(errorMessage(error, "无法刷新项目文件"));
      }
    }
    if (snapshot.status === "running") return;
    try {
      const summary = await getRunChanges(snapshot.id);
      setChanges(summary);
      const selectedChange = summary.files.find(
        (change) => change.path === activeDiffPathRef.current,
      )
        ?? summary.files[0]
        ?? null;
      activeDiffPathRef.current = selectedChange?.path ?? null;
      setActiveDiffPath(selectedChange?.path ?? null);
      if (workspaceTabRef.current === "diff" && selectedChange) {
        await openRunDiff(snapshot.id, selectedChange);
      }
    } catch (error) {
      setDiffError(errorMessage(error, "无法读取变更摘要"));
    }
    try {
      const preview = await getRunPreview(snapshot.id);
      setRunPreview(preview);
      if (!preview.available && workspaceTabRef.current === "preview") {
        workspaceTabRef.current = "code";
        setWorkspaceTab("code");
      }
    } catch {
      setRunPreview(null);
      if (workspaceTabRef.current === "preview") {
        workspaceTabRef.current = "code";
        setWorkspaceTab("code");
      }
    }
  }

  function watchRun(snapshot: RunSnapshot) {
    closeRunStream.current?.();
    closeRunStream.current = subscribeToRun(
      snapshot.id,
      (event) => {
        setRun((current) =>
          current?.id === snapshot.id
            ? {
                ...current,
                events: current.events.some((item) => item.sequence === event.sequence)
                  ? current.events
                  : [...current.events, event],
              }
            : current,
        );
        if (event.kind === "approval_required") {
          void refreshRun(snapshot.id);
        }
        if (
          event.kind === "tool_finished"
          && event.tool_name === "apply_patch"
          && event.status === "succeeded"
        ) {
          void refreshProjectWorkspace();
        }
      },
      () => void refreshRun(snapshot.id),
      () => void refreshRun(snapshot.id),
    );
  }

  async function selectSessionRun(snapshot: RunSnapshot) {
    closeRunStream.current?.();
    clearRunReview();
    setRun(snapshot);
    setRunBrief(snapshot.intent);
    await loadRunFacts(snapshot);
    if (snapshot.status === "running") watchRun(snapshot);
  }

  async function loadSessionIntoView(sessionId: string, projectId = project?.id) {
    setMessageError("");
    closeRunStream.current?.();
    clearRunReview();
    setRun(null);
    setRunBrief(null);
    setCanvasProposal(null);
    setAdoptedTaskDraft(null);
    setCanvasStorageSessionId(null);
    setActiveSessionId(sessionId);
    if (projectId) localStorage.setItem(`${ACTIVE_SESSION_KEY}.${projectId}`, sessionId);
    try {
      const detail = await getSession(sessionId);
      setApprovalMode(detail.session.approval_mode);
      setSessionMessages(detail.messages);
      setSessionRuns(detail.runs);
      setTaskDrafts(detail.task_drafts ?? []);
      const latestCanvas = detail.canvas_snapshots.at(-1)?.canvas ?? null;
      const sessionCanvas = loadSessionCanvas(sessionId, latestCanvas);
      setNodes(sessionCanvas.nodes);
      setEdges(sessionCanvas.edges);
      setEditingEdgeId(null);
      setCanvasStorageSessionId(sessionId);
      const latestRun = detail.runs.at(-1);
      if (latestRun) await selectSessionRun(latestRun);
    } catch (error) {
      setMessageError(errorMessage(error, "无法读取对话"));
    }
  }

  async function handleCreateSession() {
    if (!project) return;
    setMessageError("");
    try {
      const created = await createSession(project.id);
      setSessions((current) => [created, ...current]);
      setSessionMessages([]);
      setSessionRuns([]);
      setTaskDrafts([]);
      setCanvasProposal(null);
      setAdoptedTaskDraft(null);
      setMessageDraft("");
      await loadSessionIntoView(created.id, project.id);
    } catch (error) {
      setMessageError(errorMessage(error, "无法新建对话"));
    }
  }

  async function handleDeleteSession() {
    if (!project || !activeSessionId || sessionDeleting) return;
    if (sessionRuns.some((sessionRun) => sessionRun.status === "running")) {
      setMessageError("运行中的对话不能删除，请先停止 Agent");
      return;
    }
    const activeSession = sessions.find((session) => session.id === activeSessionId);
    const reviewWarning = sessionRuns.some((sessionRun) => sessionRun.review_status === "pending")
      ? " 待审查修改会先撤销。"
      : "";
    const confirmed = window.confirm(
      `删除对话“${activeSession?.title ?? "当前对话"}”吗？${reviewWarning}此操作会删除消息、Canvas 快照、运行历史和 Checkpoint。`,
    );
    if (!confirmed) return;

    setSessionDeleting(true);
    setMessageError("");
    try {
      closeRunStream.current?.();
      await deleteSession(activeSessionId);
      let remainingSessions = await listSessions(project.id);
      if (remainingSessions.length === 0) {
        remainingSessions = [await createSession(project.id)];
      }
      setSessions(remainingSessions);
      setSessionMessages([]);
      setSessionRuns([]);
      setTaskDrafts([]);
      setCanvasProposal(null);
      setAdoptedTaskDraft(null);
      setRun(null);
      setRunBrief(null);
      await loadSessionIntoView(remainingSessions[0].id, project.id);
    } catch (error) {
      setMessageError(errorMessage(error, "删除对话失败"));
    } finally {
      setSessionDeleting(false);
    }
  }

  async function handleSendMessage(confirmedTaskDraft: TaskDraftSnapshot | null = null) {
    const content = confirmedTaskDraft
      ? `确认并执行任务草案 v${confirmedTaskDraft.version}：${confirmedTaskDraft.intent.title}`
      : messageDraft.trim();
    if (!activeSessionId || !content) return;
    const submittedCanvas = confirmedTaskDraft
      ? toIntentCanvas(nodes, edges)
      : attachCanvas
        ? toIntentCanvas(nodes, edges)
        : null;
    const optimisticMessageId = `pending-${Date.now()}`;
    const optimisticMessage: ConversationMessage = {
      id: optimisticMessageId,
      session_id: activeSessionId,
      role: "user",
      mode: "agent",
      content,
      canvas_snapshot_id: submittedCanvas ? "pending" : null,
      task_draft_id: null,
      run_id: null,
      intent: null,
      created_at: new Date().toISOString(),
      sequence: (sessionMessages.at(-1)?.sequence ?? 0) + 1,
    };
    setSessionMessages((current) => [...current, optimisticMessage]);
    if (!confirmedTaskDraft) setMessageDraft("");
    setMessageSending(true);
    setMessageError("");
    try {
      const response = await sendSessionMessage(
        activeSessionId,
        content,
        approvalMode,
        submittedCanvas,
        confirmedTaskDraft?.id ?? null,
        confirmedTaskDraft ? false : canvasPlanMode,
      );
      setSessionMessages((current) => [
        ...current.filter((message) => message.id !== optimisticMessageId),
        response.user_message,
        response.assistant_message,
      ]);
      const createdTaskDraft = response.task_draft;
      if (createdTaskDraft) {
        setTaskDrafts((current) => [...current, createdTaskDraft]);
      }
      if (confirmedTaskDraft) setAdoptedTaskDraft(null);
      if (project) setSessions(await listSessions(project.id));

      const createdRun = response.run;
      if (createdRun) {
        clearRunReview();
        setRun(createdRun);
        setRunBrief(createdRun.intent ?? response.assistant_message.intent);
        setSessionRuns((current) => [...current, createdRun]);
        void loadRunFacts(createdRun);
        watchRun(createdRun);
      }
    } catch (error) {
      setMessageError(errorMessage(error, "消息发送失败"));
      setSessionMessages((current) => current.filter(
        (message) => message.id !== optimisticMessageId,
      ));
      try {
        const detail = await getSession(activeSessionId);
        setSessionMessages(detail.messages);
        setSessionRuns(detail.runs);
      } catch {
        // Keep the original send error visible.
      }
    } finally {
      setMessageSending(false);
      setActivityInterrupting(false);
    }
  }

  async function handleInterrupt() {
    if (!activeSessionId || (!messageSending && run?.status !== "running")) return;
    setActivityInterrupting(true);
    setMessageError("");
    try {
      const result = await cancelSessionActivity(activeSessionId);
      if (result.kind === "run" && run) {
        await refreshRun(run.id);
        setActivityInterrupting(false);
      } else if (result.kind === "none") {
        setMessageError("当前没有可中断的处理");
        setActivityInterrupting(false);
      }
    } catch (error) {
      setMessageError(errorMessage(error, "中断当前处理失败"));
      setActivityInterrupting(false);
    }
  }

  async function handleResolveApproval(approvalId: string, decision: ApprovalDecision) {
    if (!run || run.status !== "running") return;
    setToolApprovalAction({ approvalId, decision });
    setRunError("");
    try {
      const updated = await resolveRunApproval(run.id, approvalId, decision);
      setRun(updated);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === updated.id ? updated : item,
      ));
    } catch (error) {
      setRunError(errorMessage(error, "处理修改审批失败"));
    } finally {
      setToolApprovalAction(null);
    }
  }

  async function handleKeep() {
    if (!run || run.status === "running" || run.review_status !== "pending" || !changes) {
      return;
    }
    const hasVerification = (run.report?.evidence.length ?? 0) > 0;
    const riskNotice = run.status !== "completed"
      ? "当前 Agent 运行未正常完成，修改可能不完整。请先检查 Diff。\n\n"
      : !hasVerification
        ? "本次修改没有自动化验证结果，请先检查 Diff。\n\n"
        : "";
    const confirmed = window.confirm(
      `${riskNotice}当前项目已有 ${changes.changed_files} 个文件变更，确认保留本轮修改吗？`,
    );
    if (!confirmed) return;

    setReviewAction("keep");
    setReviewError("");
    try {
      const updated = await keepRun(run.id);
      setRun(updated);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === updated.id ? updated : item,
      ));
    } catch (error) {
      setReviewError(errorMessage(error, "保留修改失败"));
    } finally {
      setReviewAction(null);
    }
  }

  async function handleUndo() {
    if (!run || run.status === "running" || run.review_status !== "pending") return;
    const confirmed = window.confirm(
      "撤销本轮修改吗？系统会根据 Checkpoint 恢复本轮触碰的文件，历史 Diff 会保留。",
    );
    if (!confirmed) return;

    setReviewAction("undo");
    setReviewError("");
    try {
      const updated = await undoRun(run.id);
      setRun(updated);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === updated.id ? updated : item,
      ));
      await refreshProjectWorkspace();
    } catch (error) {
      setReviewError(errorMessage(error, "撤销本轮失败"));
    } finally {
      setReviewAction(null);
    }
  }

  async function refreshOpenProjectFiles() {
    if (!project) return;
    const refreshedFiles = await Promise.all(openFilesRef.current.map(async (openFile) => {
      try {
        const file = await getProjectFile(project.id, openFile.path);
        const dirty = Boolean(
          openFile.file && openFile.draft !== openFile.file.content,
        );
        return {
          ...openFile,
          state: "ready" as const,
          file,
          draft: dirty ? openFile.draft : file.content,
          saveError: dirty && openFile.file?.content !== file.content
            ? "项目文件已发生变化，保存前请撤销未保存内容并重新编辑"
            : openFile.saveError,
          error: "",
        };
      } catch (error) {
        return {
          ...openFile,
          state: "error" as const,
          file: null,
          error: errorMessage(error, "文件读取失败"),
        };
      }
    }));
    const refreshedByKey = new Map(refreshedFiles.map((file) => [file.key, file]));
    setOpenFiles((currentFiles) => currentFiles.map(
      (file) => refreshedByKey.get(file.key) ?? file,
    ));
  }

  async function refreshProjectWorkspace() {
    if (!project) return;
    try {
      setProjectTree(await getProjectTree(project.id));
      await refreshOpenProjectFiles();
      setPreviewRevision((current) => current + 1);
    } catch (error) {
      setWorkspaceError(errorMessage(error, "无法刷新项目文件"));
    }
  }

  function highlightSources(sourceIds: string[]) {
    setNodes((currentNodes) =>
      currentNodes.map((node) => ({ ...node, selected: sourceIds.includes(node.id) })),
    );
  }

  async function openWorkspaceFile(path: string) {
    const key = workspaceFileKey(path);
    setWorkspaceTab("code");
    setActiveFileKey(key);
    const existing = openFiles.find((file) => file.key === key);
    if (existing?.state === "ready" || existing?.state === "loading") return;

    const loadingFile: OpenWorkspaceFile = {
      key,
      path,
      state: "loading",
      file: null,
      draft: "",
      revision: 0,
      saving: false,
      saveError: "",
      error: "",
    };
    setOpenFiles((currentFiles) => {
      const exists = currentFiles.some((file) => file.key === key);
      return exists
        ? currentFiles.map((file) => file.key === key ? loadingFile : file)
        : [...currentFiles, loadingFile];
    });

    try {
      const file = project ? await getProjectFile(project.id, path) : null;
      if (!file) throw new Error("当前没有可读取的项目文件");
      setOpenFiles((currentFiles) => currentFiles.map((item) => (
        item.key === key
          ? { ...item, state: "ready", file, draft: file.content, saveError: "", error: "" }
          : item
      )));
    } catch (error) {
      setOpenFiles((currentFiles) => currentFiles.map((item) => (
        item.key === key
          ? { ...item, state: "error", file: null, error: errorMessage(error, "文件读取失败") }
          : item
      )));
    }
  }

  function closeWorkspaceFile(key: string) {
    const closingFile = openFiles.find((file) => file.key === key);
    if (
      closingFile?.file
      && closingFile.draft !== closingFile.file.content
      && !window.confirm(`关闭 ${closingFile.path} 并丢弃未保存修改吗？`)
    ) return;
    const timer = autosaveTimers.current.get(key);
    if (timer) clearTimeout(timer);
    autosaveTimers.current.delete(key);
    setOpenFiles((currentFiles) => {
      const closingIndex = currentFiles.findIndex((file) => file.key === key);
      const remaining = currentFiles.filter((file) => file.key !== key);
      if (activeFileKey === key) {
        const nextFile = remaining[Math.max(0, closingIndex - 1)] ?? remaining[0] ?? null;
        setActiveFileKey(nextFile?.key ?? null);
      }
      return remaining;
    });
  }

  function updateWorkspaceFileDraft(key: string, content: string) {
    setOpenFiles((currentFiles) => currentFiles.map((file) => (
      file.key === key
        ? { ...file, draft: content, revision: file.revision + 1, saveError: "" }
        : file
    )));
    scheduleWorkspaceAutosave(key);
  }

  async function saveWorkspaceFile(key: string) {
    const openFile = openFilesRef.current.find((file) => file.key === key);
    if (!project || !openFile?.file || openFile.draft === openFile.file.content) return;
    if (openFile.saving) {
      scheduleWorkspaceAutosave(key, 200);
      return;
    }
    if (pendingReviewRun?.status === "running") return;
    const savedRevision = openFile.revision;
    const editableRun = pendingReviewRun;
    setOpenFiles((currentFiles) => currentFiles.map((file) => (
      file.key === key ? { ...file, saving: true, saveError: "" } : file
    )));
    try {
      const response = await updateProjectFile(
        project.id,
        openFile.path,
        openFile.draft,
        openFile.file.content,
        editableRun?.id ?? null,
      );
      setOpenFiles((currentFiles) => currentFiles.map((file) => (
        file.key === key
          ? {
              ...file,
              state: "ready",
              file: response.file,
              draft: file.revision === savedRevision ? response.file.content : file.draft,
              saving: false,
              saveError: "",
              error: "",
            }
          : file
      )));
      if (response.run) {
        setRun(response.run);
        setRunBrief(response.run.intent);
        setSessionRuns((currentRuns) => currentRuns.map(
          (item) => item.id === response.run?.id ? response.run : item,
        ));
      }
      if (response.changes) {
        setChanges(response.changes);
        setActiveDiff(null);
        setActiveDiffPath(response.changes.files[0]?.path ?? null);
      }
      setPreviewRevision((current) => current + 1);
      scheduleWorkspaceAutosave(key, 150);
    } catch (error) {
      setOpenFiles((currentFiles) => currentFiles.map((file) => (
        file.key === key
          ? { ...file, saving: false, saveError: errorMessage(error, "文件保存失败") }
          : file
      )));
    }
  }

  function scheduleWorkspaceAutosave(key: string, delay = 500) {
    const existing = autosaveTimers.current.get(key);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(() => {
      autosaveTimers.current.delete(key);
      void saveWorkspaceFile(key);
    }, delay);
    autosaveTimers.current.set(key, timer);
  }

  async function openRunDiff(runId: string, change: FileChange) {
    const requestSequence = diffRequestSequence.current + 1;
    diffRequestSequence.current = requestSequence;
    workspaceTabRef.current = "diff";
    activeDiffPathRef.current = change.path;
    setWorkspaceTab("diff");
    setActiveDiffPath(change.path);
    setActiveDiff(null);
    setDiffError("");
    if (!change.viewable) {
      setDiffLoading(false);
      return;
    }

    setDiffLoading(true);
    try {
      const loadedDiff = await getRunFileDiff(runId, change.path);
      if (diffRequestSequence.current === requestSequence) setActiveDiff(loadedDiff);
    } catch (error) {
      if (diffRequestSequence.current === requestSequence) {
        setDiffError(errorMessage(error, "Diff 读取失败"));
      }
    } finally {
      if (diffRequestSequence.current === requestSequence) setDiffLoading(false);
    }
  }

  function selectWorkspaceTab(tab: WorkspaceTab) {
    workspaceTabRef.current = tab;
    if (tab !== "canvas") setEditingEdgeId(null);
    setWorkspaceTab(tab);
    if (tab !== "diff" || !run || run.status === "running") return;
    const selectedChange = changes?.files.find((change) => change.path === activeDiffPath)
      ?? changes?.files[0];
    if (selectedChange && activeDiff?.path !== selectedChange.path) {
      void openRunDiff(run.id, selectedChange);
    }
  }

  async function openRelatedFile(path: string) {
    if (!run) {
      await openWorkspaceFile(path);
      return;
    }
    let currentChanges = changes;
    if (run.status !== "running" && !currentChanges) {
      try {
        currentChanges = await getRunChanges(run.id);
        setChanges(currentChanges);
      } catch (error) {
        setDiffError(errorMessage(error, "无法判断文件变更状态"));
      }
    }
    if (relatedFileDestination(currentChanges, path) === "diff") {
      const change = currentChanges?.files.find((item) => item.path === path);
      if (change) await openRunDiff(run.id, change);
      return;
    }
    await openWorkspaceFile(path);
  }

  const statusText = {
    checking: "正在连接后端",
    connected: "后端已连接",
    failed: "后端连接失败",
  }[connection];
  const pendingReviewRun = [...sessionRuns]
    .reverse()
    .find((sessionRun) => sessionRun.review_status === "pending") ?? null;
  const agentBlockReason = pendingReviewRun?.status === "running"
    ? "当前 Agent 运行结束并处理修改后才能开始下一轮"
    : pendingReviewRun
      ? "请先保留或撤销上一轮 Agent 修改"
      : "";
  const runStatusText = run
    ? { running: "运行中", completed: "已完成", failed: "失败", stopped: "已停止" }[run.status]
    : "待运行";
  const verifiedRequirements = run?.report?.requirement_results.filter(
    (result) => result.status === "verified",
  ).length ?? 0;
  const reviewStatusText = run
    ? { pending: "待审查", accepted: "已保留", discarded: "已撤销" }[run.review_status]
    : "待运行";
  const selectedRunDetail = run && runBrief ? (
    <SingleRunConversation
      brief={runBrief}
      run={run}
      runError={runError}
      changes={changes}
      reviewAction={reviewAction}
      toolApprovalAction={toolApprovalAction}
      reviewError={reviewError}
      onHighlightSources={highlightSources}
      onOpenRelatedFile={(path) => void openRelatedFile(path)}
      onKeep={() => void handleKeep()}
      onUndo={() => void handleUndo()}
      onResolveApproval={(approvalId, decision) => {
        void handleResolveApproval(approvalId, decision);
      }}
      showIntentContext={!run.session_id}
    />
  ) : null;
  const previewCanvas = canvasProposal?.canvas
    ? fromIntentCanvas(canvasProposal.canvas)
    : null;

  return (
    <main className="workspace-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true"><Sparkles size={17} /></div>
          <span className="brand-name">IntentFlow</span>
          <span className="project-separator">/</span>
          {project ? (
            <select
              className="project-switcher"
              aria-label="当前项目"
              value={project.id}
              disabled={projectBusy || messageSending || run?.status === "running"}
              title={project.root_path}
              onChange={(event) => void handleProjectSwitch(event.target.value)}
            >
              {projects.map((item) => (
                <option value={item.id} key={item.id}>{item.name}</option>
              ))}
            </select>
          ) : (
            <span className="project-name">未选择项目</span>
          )}
          <button
            className="project-manage-button"
            type="button"
            aria-label="项目管理"
            title="添加项目或修改项目设置"
            disabled={projectBusy || messageSending || run?.status === "running"}
            onClick={() => {
              setProjectError("");
              setProjectDialogOpen(true);
            }}
          >
            <Settings2 size={14} />
          </button>
        </div>
        <div className="topbar-actions">
          <div className={`connection-state connection-state--${connection}`}>
            <span className="connection-dot" aria-hidden="true" />{statusText}
          </div>
        </div>
      </header>

      <div
        className="workspace-grid"
        style={{ gridTemplateColumns: `240px minmax(80px, 1fr) ${conversationWidth}px` }}
      >
        <ProjectExplorer
          projectTree={projectTree}
          activeFileKey={activeFileKey}
          error={workspaceError}
          onOpenFile={(path) => void openWorkspaceFile(path)}
        />

        <section className="main-workspace">
          <div className="workspace-tabs" role="tablist" aria-label="主工作区">
            <button
              className={workspaceTab === "canvas" ? "workspace-tab--active" : ""}
              type="button"
              role="tab"
              onClick={() => selectWorkspaceTab("canvas")}
            >
              <CircleDot size={13} />Canvas
            </button>
            <button
              className={workspaceTab === "code" ? "workspace-tab--active" : ""}
              type="button"
              role="tab"
              onClick={() => selectWorkspaceTab("code")}
            >
              <FileCode2 size={13} />代码
              {openFiles.length > 0 && <span>{openFiles.length}</span>}
            </button>
            <button
              className={workspaceTab === "diff" ? "workspace-tab--active" : ""}
              type="button"
              role="tab"
              onClick={() => selectWorkspaceTab("diff")}
            >
              <GitCompareArrows size={13} />Diff
              {changes && <span>{changes.changed_files}</span>}
            </button>
            {runPreview?.available && (
              <button
                className={workspaceTab === "preview" ? "workspace-tab--active" : ""}
                type="button"
                role="tab"
                title="查看网页结果"
                onClick={() => selectWorkspaceTab("preview")}
              >
                <MonitorPlay size={13} />预览
              </button>
            )}
          </div>
          <div className="workspace-view">
            {workspaceTab === "canvas" ? (
              <div className="canvas-workspace">
                {canvasProposal ? (
                  <div className="canvas-toolbar canvas-toolbar--proposal">
                    <span>正在预览任务草案 v{canvasProposal.version} 的 Canvas 摘要</span>
                    <div className="canvas-toolbar__actions">
                      <button type="button" onClick={adoptCanvasProposal}>采用到 Canvas</button>
                      <button type="button" onClick={() => setCanvasProposal(null)}>退出预览</button>
                    </div>
                  </div>
                ) : (
                  <div className="canvas-toolbar">
                    <button type="button" onClick={addNote}><Plus size={13} />添加便签</button>
                    <button type="button" onClick={restoreExample}><RotateCcw size={13} />恢复示例</button>
                    <button type="button" onClick={clearCanvas}><Trash2 size={13} />清空</button>
                    {adoptedTaskDraft && (
                      <button
                        className="canvas-confirm-button"
                        type="button"
                        disabled={messageSending || Boolean(pendingReviewRun)}
                        onClick={() => void handleSendMessage(adoptedTaskDraft)}
                      >
                        确认并执行 v{adoptedTaskDraft.version}
                      </button>
                    )}
                  </div>
                )}
                <div
                  className="canvas-panel"
                  onKeyDownCapture={handleCanvasKeyDown}
                >
                  <div className="canvas-header">
                    <span>{canvasProposal ? "Agent 规划摘要" : "Intent Canvas"}</span>
                    <span>
                      {previewCanvas?.nodes.length ?? nodes.length} 张便签 · {previewCanvas?.edges.length ?? edges.length} 条关系
                    </span>
                  </div>
                  <NoteNodeProvider callbacks={callbacks}>
                    <EditableEdgeProvider callbacks={edgeCallbacks}>
                      <ReactFlow<NoteNodeType>
                        key={canvasProposal?.id ?? canvasStorageSessionId ?? "canvas"}
                        fitView
                        nodes={previewCanvas?.nodes ?? nodes}
                        edges={previewCanvas?.edges ?? edges}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        minZoom={0.55} maxZoom={1.45}
                        zoomOnDoubleClick={false}
                        nodesDraggable={!canvasProposal}
                        nodesConnectable={!canvasProposal}
                        deleteKeyCode={canvasProposal ? null : ["Backspace", "Delete"]}
                        onConnect={canvasProposal ? undefined : onConnect}
                        onNodesChange={canvasProposal ? undefined : onNodesChange}
                        onEdgesChange={canvasProposal ? undefined : onEdgesChange}
                        onEdgeDoubleClick={canvasProposal ? undefined : (event, edge) => {
                          event.preventDefault();
                          event.stopPropagation();
                          setEditingEdgeId(edge.id);
                        }}
                        onPaneClick={() => setEditingEdgeId(null)}
                      >
                        <Background
                          color="#d6d5cf" gap={20} size={1}
                          variant={BackgroundVariant.Dots}
                        />
                      </ReactFlow>
                    </EditableEdgeProvider>
                  </NoteNodeProvider>
                </div>
              </div>
            ) : workspaceTab === "code" ? (
              <CodeWorkspace
                files={openFiles}
                activeFileKey={activeFileKey}
                editable={!pendingReviewRun || pendingReviewRun.status !== "running"}
                onSelectFile={setActiveFileKey}
                onCloseFile={closeWorkspaceFile}
                onChangeFile={updateWorkspaceFileDraft}
              />
            ) : workspaceTab === "diff" ? (
              <DiffWorkspace
                changes={changes}
                activePath={activeDiffPath}
                diff={activeDiff}
                loading={diffLoading}
                error={diffError}
                onSelectChange={(change) => {
                  if (run) void openRunDiff(run.id, change);
                }}
              />
            ) : (
              <div className="preview-workspace">
                {runPreview?.available && runPreview.url ? (
                  <iframe
                    key={`${runPreview.url}:${previewRevision}`}
                    src={`${runPreview.url}?revision=${previewRevision}`}
                    title={`${project?.name ?? "项目"}构建预览`}
                    sandbox="allow-scripts"
                  />
                ) : (
                  <div className="workspace-empty">
                    <MonitorPlay size={28} />
                    <strong>暂无可预览的构建结果</strong>
                    <p>Agent 成功生成 dist/index.html 后会在这里提供项目预览。</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <div className="conversation-panel-wrap">
          <button
            className="conversation-resizer"
            type="button"
            aria-label="调整对话区宽度"
            title="拖动调整对话区宽度"
            onPointerDown={(event) => {
              event.preventDefault();
              setIsResizingConversation(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                setConversationWidth((width) => clampConversationWidth(width + 20));
              }
              if (event.key === "ArrowRight") {
                event.preventDefault();
                setConversationWidth((width) => clampConversationWidth(width - 20));
              }
            }}
          />
          <aside className="run-panel intent-panel">
            <div className="panel-heading session-heading">
              <select
                aria-label="当前对话"
                value={activeSessionId ?? ""}
                disabled={sessions.length === 0 || messageSending || sessionDeleting}
                onChange={(event) => void loadSessionIntoView(event.target.value)}
              >
                {sessions.map((session) => (
                  <option value={session.id} key={session.id}>{session.title}</option>
                ))}
              </select>
              <button
                type="button"
                title="新建对话"
                aria-label="新建对话"
                disabled={messageSending || sessionDeleting}
                onClick={() => void handleCreateSession()}
              >
                <MessageSquarePlus size={15} />
              </button>
              <button
                type="button"
                title="删除当前对话"
                aria-label="删除当前对话"
                disabled={!activeSessionId || messageSending || sessionDeleting}
                onClick={() => void handleDeleteSession()}
              >
                <Trash2 size={15} />
              </button>
              <span className={`run-state run-state--${run?.status ?? "idle"}`}>
                {run ? runStatusText : messageSending ? "处理中" : "待命"}
              </span>
            </div>
            <div className="conversation-scroll">
              <SessionConversation
                messages={sessionMessages}
                runs={sessionRuns}
                taskDrafts={taskDrafts}
                selectedRunId={run?.id ?? null}
                selectedRunDetail={selectedRunDetail}
                responding={messageSending}
                onSelectRun={(selectedRun) => void selectSessionRun(selectedRun)}
                onPreviewTaskDraft={previewTaskDraft}
              />
              {run && !run.session_id && selectedRunDetail}
            </div>
            <ConversationComposer
              value={messageDraft}
              approvalMode={approvalMode}
              attachCanvas={attachCanvas}
              canvasPlanMode={canvasPlanMode}
              sending={messageSending}
              activityRunning={run?.status === "running"}
              interrupting={activityInterrupting}
              pendingReviewNotice={agentBlockReason}
              error={messageError}
              onChange={setMessageDraft}
              onApprovalModeChange={setApprovalMode}
              onAttachCanvasChange={setAttachCanvas}
              onCanvasPlanModeChange={setCanvasPlanMode}
              onSubmit={() => void handleSendMessage()}
              onInterrupt={() => void handleInterrupt()}
            />
          </aside>
        </div>
      </div>

      <footer className="statusbar">
        <span>运行：{runStatusText}</span>
        <span className="statusbar-divider" />
        <button
          className="statusbar-link"
          type="button"
          disabled={!changes}
          onClick={() => selectWorkspaceTab("diff")}
        >
          变更：{changes ? `${changes.changed_files} 个文件` : "待生成"}
        </button>
        <span className="statusbar-divider" />
        <span>
          验证：{run?.report
            ? `${verifiedRequirements}/${run.report.requirement_results.length} 项已验证`
            : "待验证"}
        </span>
        <span className="statusbar-divider" />
        <span>审查：{reviewStatusText}</span>
      </footer>

      <ProjectDialog
        open={projectsReady && (projectDialogOpen || !project?.ready)}
        required={!project?.ready}
        project={project}
        busy={projectBusy}
        error={projectError}
        onClose={() => setProjectDialogOpen(false)}
        onPickExisting={() => void handlePickProject()}
        onPickParent={handlePickParent}
        onRegisterPath={(path) => void handleRegisterProject(path)}
        onCreate={(parentPath, name, template) => {
          void handleCreateProject(parentPath, name, template);
        }}
        onSave={(updatedProject) => void handleSaveProject(updatedProject)}
      />
    </main>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
