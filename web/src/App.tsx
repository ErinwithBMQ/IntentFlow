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
  Link2,
  MessageSquarePlus,
  Plus,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  TODO_EXAMPLE_EDGES,
  TODO_EXAMPLE_NODES,
  isStoredCanvas,
  toIntentCanvas,
  type NoteNode as NoteNodeType,
} from "./features/canvas/canvasState";
import { NoteNode, NoteNodeProvider } from "./features/canvas/NoteNode";
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
  acceptRun,
  cancelSessionActivity,
  createSession,
  deleteSession,
  discardRun,
  getHealth,
  getProject,
  getProjectFile,
  getProjectTree,
  getRun,
  getRunChanges,
  getRunFile,
  getRunFileDiff,
  getRunTree,
  getSession,
  listSessions,
  resolveRunApproval,
  sendSessionMessage,
  subscribeToRun,
  type CanvasNoteLabel,
  type ChangeSummary,
  type ApprovalDecision,
  type ApprovalMode,
  type ConversationMessage,
  type FileChange,
  type FileDiff,
  type IntentBrief,
  type ProjectResponse,
  type RunSnapshot,
  type SessionRecord,
  type WorkspaceScope,
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

function loadCanvas() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as unknown;
    if (isStoredCanvas(stored)) return stored;
  } catch {
    // Ignore invalid local data and restore the stable demo canvas.
  }
  return {
    nodes: TODO_EXAMPLE_NODES,
    edges: TODO_EXAMPLE_EDGES,
    supplementalText: "这个功能要适合两分钟内现场演示。",
  };
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
  const [supplementalText, setSupplementalText] = useState(initialCanvas.supplementalText);
  const [connectionLabel, setConnectionLabel] = useState("相关");
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [runBrief, setRunBrief] = useState<IntentBrief | null>(null);
  const [runError, setRunError] = useState("");
  const [reviewAction, setReviewAction] = useState<"accept" | "discard" | null>(null);
  const [toolApprovalAction, setToolApprovalAction] = useState<{
    approvalId: string;
    decision: ApprovalDecision;
  } | null>(null);
  const [reviewError, setReviewError] = useState("");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("canvas");
  const [projectTree, setProjectTree] = useState<WorkspaceTree | null>(null);
  const [runTree, setRunTree] = useState<WorkspaceTree | null>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [openFiles, setOpenFiles] = useState<OpenWorkspaceFile[]>([]);
  const [activeFileKey, setActiveFileKey] = useState<string | null>(null);
  const [changes, setChanges] = useState<ChangeSummary | null>(null);
  const [activeDiffPath, setActiveDiffPath] = useState<string | null>(null);
  const [activeDiff, setActiveDiff] = useState<FileDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState("");
  const [conversationWidth, setConversationWidth] = useState(loadConversationWidth);
  const [isResizingConversation, setIsResizingConversation] = useState(false);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionMessages, setSessionMessages] = useState<ConversationMessage[]>([]);
  const [sessionRuns, setSessionRuns] = useState<RunSnapshot[]>([]);
  const [messageDraft, setMessageDraft] = useState("");
  const [approvalMode, setApprovalMode] = useState<ApprovalMode>("ask");
  const [attachCanvas, setAttachCanvas] = useState(false);
  const [messageSending, setMessageSending] = useState(false);
  const [activityInterrupting, setActivityInterrupting] = useState(false);
  const [sessionDeleting, setSessionDeleting] = useState(false);
  const [messageError, setMessageError] = useState("");
  const closeRunStream = useRef<(() => void) | null>(null);
  const diffRequestSequence = useRef(0);
  const workspaceTabRef = useRef<WorkspaceTab>("canvas");
  const activeDiffPathRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [health, projectInfo, availableSessions] = await Promise.all([
          getHealth(),
          getProject(),
          listSessions(),
        ]);
        if (active && health.status === "ok") {
          setConnection("connected");
          setProject(projectInfo);
          try {
            setProjectTree(await getProjectTree());
          } catch (error) {
            setWorkspaceError(errorMessage(error, "无法读取项目文件"));
          }

          const storedSessionId = localStorage.getItem(ACTIVE_SESSION_KEY);
          let selectedSession = availableSessions.find(
            (session) => session.id === storedSessionId,
          ) ?? availableSessions[0];
          if (!selectedSession) {
            selectedSession = await createSession();
            availableSessions.unshift(selectedSession);
          }
          if (!active) return;
          setSessions(availableSessions);
          setActiveSessionId(selectedSession.id);
          setApprovalMode(selectedSession.approval_mode);
          localStorage.setItem(ACTIVE_SESSION_KEY, selectedSession.id);

          const detail = await getSession(selectedSession.id);
          if (!active) return;
          setSessionMessages(detail.messages);
          setSessionRuns(detail.runs);
          const latestRun = detail.runs.at(-1) ?? null;
          setRun(latestRun);
          setRunBrief(latestRun?.intent ?? null);
          if (latestRun) {
            try {
              setRunTree(await getRunTree(latestRun.id));
              if (latestRun.status !== "running") {
                setChanges(await getRunChanges(latestRun.id));
              } else {
                const refreshRestoredRun = async () => {
                  try {
                    const snapshot = await getRun(latestRun.id);
                    if (!active) return;
                    setRun(snapshot);
                    setSessionRuns((currentRuns) => currentRuns.map(
                      (item) => item.id === snapshot.id ? snapshot : item,
                    ));
                    setRunTree(await getRunTree(snapshot.id));
                    if (snapshot.status !== "running") {
                      setChanges(await getRunChanges(snapshot.id));
                    }
                  } catch (error) {
                    if (active) {
                      setRunError(errorMessage(error, "无法读取运行结果"));
                    }
                  }
                };
                closeRunStream.current = subscribeToRun(
                  latestRun.id,
                  (event) => {
                    setRun((current) => current?.id === latestRun.id
                      ? {
                          ...current,
                          events: current.events.some((item) => item.sequence === event.sequence)
                            ? current.events
                            : [...current.events, event],
                        }
                      : current);
                  },
                  () => void refreshRestoredRun(),
                  () => void refreshRestoredRun(),
                );
              }
            } catch (error) {
              setWorkspaceError(errorMessage(error, "无法恢复运行工作区"));
            }
          }
        }
      } catch (error) {
        if (active) {
          setConnection("failed");
          setWorkspaceError(errorMessage(error, "无法读取项目文件"));
        }
      }
    }
    void bootstrap();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes, edges, supplementalText }));
  }, [edges, nodes, supplementalText]);

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
    },
    [setEdges, setNodes],
  );

  const callbacks = useMemo(
    () => ({ onChange: updateNote, onRemove: removeNote }),
    [removeNote, updateNote],
  );

  const onConnect = useCallback(
    (params: Connection) => {
      setEdges((currentEdges) =>
        addEdge({ ...params, label: connectionLabel.trim() || "相关" }, currentEdges),
      );
    },
    [connectionLabel, setEdges],
  );

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
    setNodes(TODO_EXAMPLE_NODES.map((node) => ({ ...node, data: { ...node.data } })));
    setEdges(TODO_EXAMPLE_EDGES.map((edge) => ({ ...edge })));
    setSupplementalText("这个功能要适合两分钟内现场演示。");
  }

  function clearRunReview() {
    diffRequestSequence.current += 1;
    activeDiffPathRef.current = null;
    setRunTree(null);
    setChanges(null);
    setActiveDiffPath(null);
    setActiveDiff(null);
    setDiffError("");
    setDiffLoading(false);
    setReviewAction(null);
    setReviewError("");
    setOpenFiles((currentFiles) => currentFiles.filter((file) => file.scope === "project"));
    if (activeFileKey?.startsWith("run:")) {
      setActiveFileKey(openFiles.find((file) => file.scope === "project")?.key ?? null);
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
    try {
      setRunTree(await getRunTree(snapshot.id));
    } catch (error) {
      setWorkspaceError(errorMessage(error, "无法读取 Agent 修改版本"));
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

  async function loadSessionIntoView(sessionId: string) {
    setMessageError("");
    closeRunStream.current?.();
    clearRunReview();
    setRun(null);
    setRunBrief(null);
    setActiveSessionId(sessionId);
    localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
    try {
      const detail = await getSession(sessionId);
      setApprovalMode(detail.session.approval_mode);
      setSessionMessages(detail.messages);
      setSessionRuns(detail.runs);
      const latestRun = detail.runs.at(-1);
      if (latestRun) await selectSessionRun(latestRun);
    } catch (error) {
      setMessageError(errorMessage(error, "无法读取对话"));
    }
  }

  async function handleCreateSession() {
    setMessageError("");
    try {
      const created = await createSession();
      setSessions((current) => [created, ...current]);
      setSessionMessages([]);
      setSessionRuns([]);
      setMessageDraft("");
      await loadSessionIntoView(created.id);
    } catch (error) {
      setMessageError(errorMessage(error, "无法新建对话"));
    }
  }

  async function handleDeleteSession() {
    if (!activeSessionId || sessionDeleting) return;
    if (sessionRuns.some((sessionRun) => sessionRun.status === "running")) {
      setMessageError("运行中的对话不能删除，请先停止 Agent");
      return;
    }
    const activeSession = sessions.find((session) => session.id === activeSessionId);
    const reviewWarning = sessionRuns.some((sessionRun) => sessionRun.review_status === "pending")
      ? " 未应用的修改也会一并放弃。"
      : "";
    const confirmed = window.confirm(
      `删除对话“${activeSession?.title ?? "当前对话"}”吗？${reviewWarning}此操作会删除消息、Canvas 快照、运行历史和隔离副本，但不会修改项目当前版本。`,
    );
    if (!confirmed) return;

    setSessionDeleting(true);
    setMessageError("");
    try {
      closeRunStream.current?.();
      await deleteSession(activeSessionId);
      let remainingSessions = await listSessions();
      if (remainingSessions.length === 0) {
        remainingSessions = [await createSession()];
      }
      setSessions(remainingSessions);
      setSessionMessages([]);
      setSessionRuns([]);
      setRun(null);
      setRunBrief(null);
      await loadSessionIntoView(remainingSessions[0].id);
    } catch (error) {
      setMessageError(errorMessage(error, "删除对话失败"));
    } finally {
      setSessionDeleting(false);
    }
  }

  async function handleSendMessage() {
    if (!activeSessionId || !messageDraft.trim()) return;
    const content = messageDraft.trim();
    const optimisticMessageId = `pending-${Date.now()}`;
    const optimisticMessage: ConversationMessage = {
      id: optimisticMessageId,
      session_id: activeSessionId,
      role: "user",
      mode: "agent",
      content,
      canvas_snapshot_id: attachCanvas ? "pending" : null,
      run_id: null,
      intent: null,
      created_at: new Date().toISOString(),
      sequence: (sessionMessages.at(-1)?.sequence ?? 0) + 1,
    };
    setSessionMessages((current) => [...current, optimisticMessage]);
    setMessageDraft("");
    setMessageSending(true);
    setMessageError("");
    try {
      const response = await sendSessionMessage(
        activeSessionId,
        content,
        approvalMode,
        attachCanvas ? toIntentCanvas(nodes, edges, supplementalText) : null,
      );
      setSessionMessages((current) => [
        ...current.filter((message) => message.id !== optimisticMessageId),
        response.user_message,
        response.assistant_message,
      ]);
      setSessions(await listSessions());

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

  async function handleAccept() {
    if (!run || run.status !== "completed" || run.review_status !== "pending" || !changes) {
      return;
    }
    const confirmed = window.confirm(
      `接受本次运行的 ${changes.changed_files} 个文件变更并写入项目当前版本吗？`,
    );
    if (!confirmed) return;

    setReviewAction("accept");
    setReviewError("");
    try {
      const updated = await acceptRun(run.id);
      setRun(updated);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === updated.id ? updated : item,
      ));
      setProjectTree(await getProjectTree());
      await refreshOpenProjectFiles();
    } catch (error) {
      setReviewError(errorMessage(error, "接受修改失败"));
    } finally {
      setReviewAction(null);
    }
  }

  async function handleDiscard() {
    if (!run || run.status === "running" || run.review_status !== "pending") return;
    const confirmed = window.confirm(
      "放弃本次修改吗？项目当前版本不会变化，Agent 修改版本和 Diff 会保留。",
    );
    if (!confirmed) return;

    setReviewAction("discard");
    setReviewError("");
    try {
      const updated = await discardRun(run.id);
      setRun(updated);
      setSessionRuns((currentRuns) => currentRuns.map(
        (item) => item.id === updated.id ? updated : item,
      ));
    } catch (error) {
      setReviewError(errorMessage(error, "放弃修改失败"));
    } finally {
      setReviewAction(null);
    }
  }

  async function refreshOpenProjectFiles() {
    const projectFiles = openFiles.filter((file) => file.scope === "project");
    const refreshedFiles = await Promise.all(projectFiles.map(async (openFile) => {
      try {
        const file = await getProjectFile(openFile.path);
        return { ...openFile, state: "ready" as const, file, error: "" };
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

  function highlightSources(sourceIds: string[]) {
    setNodes((currentNodes) =>
      currentNodes.map((node) => ({ ...node, selected: sourceIds.includes(node.id) })),
    );
  }

  async function openWorkspaceFile(scope: WorkspaceScope, path: string) {
    const key = workspaceFileKey(scope, path);
    setWorkspaceTab("code");
    setActiveFileKey(key);
    const existing = openFiles.find((file) => file.key === key);
    if (existing?.state === "ready" || existing?.state === "loading") return;

    const loadingFile: OpenWorkspaceFile = {
      key,
      scope,
      path,
      state: "loading",
      file: null,
      error: "",
    };
    setOpenFiles((currentFiles) => {
      const exists = currentFiles.some((file) => file.key === key);
      return exists
        ? currentFiles.map((file) => file.key === key ? loadingFile : file)
        : [...currentFiles, loadingFile];
    });

    try {
      const file = scope === "project"
        ? await getProjectFile(path)
        : run
          ? await getRunFile(run.id, path)
          : null;
      if (!file) throw new Error("当前没有可读取的 Agent 修改版本");
      setOpenFiles((currentFiles) => currentFiles.map((item) => (
        item.key === key ? { ...item, state: "ready", file, error: "" } : item
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
      await openWorkspaceFile("project", path);
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
    await openWorkspaceFile("run", path);
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
      ? "请先应用或放弃上一轮 Agent 修改"
      : "";
  const runStatusText = run
    ? { running: "运行中", completed: "已完成", failed: "失败", stopped: "已停止" }[run.status]
    : "待运行";
  const activeOpenFile = openFiles.find((file) => file.key === activeFileKey) ?? null;
  const workspaceLabel = workspaceTab === "canvas"
    ? "Intent Canvas"
    : workspaceTab === "diff"
      ? "本次运行 Diff"
      : activeOpenFile
        ? `${activeOpenFile.scope === "project" ? "项目当前版本" : "Agent 修改版本"} / ${activeOpenFile.path}`
        : "代码查看";
  const verifiedRequirements = run?.report?.requirement_results.filter(
    (result) => result.status === "verified",
  ).length ?? 0;
  const reviewStatusText = run
    ? { pending: "待审查", accepted: "已应用", discarded: "已放弃" }[run.review_status]
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
      onAccept={() => void handleAccept()}
      onDiscard={() => void handleDiscard()}
      onResolveApproval={(approvalId, decision) => {
        void handleResolveApproval(approvalId, decision);
      }}
      showIntentContext={!run.session_id}
    />
  ) : null;

  return (
    <main className="workspace-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true"><Sparkles size={17} /></div>
          <span className="brand-name">IntentFlow</span>
          <span className="project-separator">/</span>
          <span className="project-name">{project?.name ?? "todo-demo"}</span>
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
          runTree={runTree}
          runId={run?.id ?? null}
          activeFileKey={activeFileKey}
          error={workspaceError}
          onOpenFile={(scope, path) => void openWorkspaceFile(scope, path)}
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
          </div>
          <div className="workspace-view">
            {workspaceTab === "canvas" ? (
              <div className="canvas-workspace">
                <div className="canvas-toolbar">
                  <button type="button" onClick={addNote}><Plus size={13} />添加便签</button>
                  <button type="button" onClick={restoreExample}><RotateCcw size={13} />恢复示例</button>
                  <label>
                    <span><Link2 size={12} />连线文字</span>
                    <input
                      value={connectionLabel}
                      placeholder="例如：然后、参考"
                      onChange={(event) => setConnectionLabel(event.target.value)}
                    />
                  </label>
                  <label className="canvas-toolbar__supplement">
                    <span>补充说明</span>
                    <input
                      value={supplementalText}
                      placeholder="还有一些不好放进便签的话……"
                      onChange={(event) => setSupplementalText(event.target.value)}
                    />
                  </label>
                </div>
                <div className="canvas-panel">
                  <div className="canvas-header">
                    <span>Intent Canvas</span>
                    <span>{nodes.length} 张便签 · {edges.length} 条关系 · 已自动保存</span>
                  </div>
                  <NoteNodeProvider callbacks={callbacks}>
                    <ReactFlow<NoteNodeType>
                      fitView nodes={nodes} edges={edges} nodeTypes={nodeTypes}
                      minZoom={0.55} maxZoom={1.45}
                      onConnect={onConnect} onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                    >
                      <Background
                        color="#d6d5cf" gap={20} size={1}
                        variant={BackgroundVariant.Dots}
                      />
                    </ReactFlow>
                  </NoteNodeProvider>
                </div>
              </div>
            ) : workspaceTab === "code" ? (
              <CodeWorkspace
                files={openFiles}
                activeFileKey={activeFileKey}
                onSelectFile={setActiveFileKey}
                onCloseFile={closeWorkspaceFile}
              />
            ) : (
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
                selectedRunId={run?.id ?? null}
                selectedRunDetail={selectedRunDetail}
                responding={messageSending}
                onSelectRun={(selectedRun) => void selectSessionRun(selectedRun)}
              />
              {run && !run.session_id && selectedRunDetail}
            </div>
            <ConversationComposer
              value={messageDraft}
              approvalMode={approvalMode}
              attachCanvas={attachCanvas}
              sending={messageSending}
              activityRunning={run?.status === "running"}
              interrupting={activityInterrupting}
              pendingReviewNotice={agentBlockReason}
              error={messageError}
              onChange={setMessageDraft}
              onApprovalModeChange={setApprovalMode}
              onAttachCanvasChange={setAttachCanvas}
              onSubmit={() => void handleSendMessage()}
              onInterrupt={() => void handleInterrupt()}
            />
          </aside>
        </div>
      </div>

      <footer className="statusbar">
        <span>工作区：{workspaceLabel}</span>
        <span className="statusbar-divider" />
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
        <span className="statusbar-spacer" /><span>v0.7.0 · unified Agent context</span>
      </footer>
    </main>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
