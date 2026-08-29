import {
  Background,
  BackgroundVariant,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ArrowRight,
  Check,
  CircleDot,
  FileCode2,
  GitCompareArrows,
  Link2,
  LoaderCircle,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  TODO_EXAMPLE_EDGES,
  TODO_EXAMPLE_NODES,
  edgeChangesInvalidateIntent,
  isStoredCanvas,
  nodeChangesInvalidateIntent,
  toIntentCanvas,
  type NoteNode as NoteNodeType,
} from "./features/canvas/canvasState";
import { NoteNode, NoteNodeProvider } from "./features/canvas/NoteNode";
import { SingleRunConversation } from "./features/run/SingleRunConversation";
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
  compileIntent,
  createRun,
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
  stopRun,
  subscribeToRun,
  type CanvasNoteLabel,
  type ChangeSummary,
  type FileChange,
  type FileDiff,
  type IntentBrief,
  type ProjectResponse,
  type RunSnapshot,
  type WorkspaceScope,
  type WorkspaceTree,
} from "./services/api";

type ConnectionState = "checking" | "connected" | "failed";
type CompileState = "idle" | "compiling" | "completed" | "failed";
type CompilerKind = "ai" | "local";

const phases = ["表达想法", "整理意图", "修改代码", "运行验证", "审查修改"];
const STORAGE_KEY = "intentflow.canvas.v1";
const CONVERSATION_WIDTH_KEY = "intentflow.conversation-width.v1";
const MIN_CONVERSATION_WIDTH = 300;
const MAX_CONVERSATION_WIDTH = 640;
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
  return Math.min(MAX_CONVERSATION_WIDTH, Math.max(MIN_CONVERSATION_WIDTH, width));
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
  const [brief, setBrief] = useState<IntentBrief | null>(null);
  const [compilerKind, setCompilerKind] = useState<CompilerKind | null>(null);
  const [compilerNotice, setCompilerNotice] = useState("");
  const [compileState, setCompileState] = useState<CompileState>("idle");
  const [compileError, setCompileError] = useState("");
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [runBrief, setRunBrief] = useState<IntentBrief | null>(null);
  const [runError, setRunError] = useState("");
  const [reviewAction, setReviewAction] = useState<"accept" | "discard" | null>(null);
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
  const closeRunStream = useRef<(() => void) | null>(null);
  const diffRequestSequence = useRef(0);
  const workspaceTabRef = useRef<WorkspaceTab>("canvas");
  const activeDiffPathRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [health, projectInfo] = await Promise.all([getHealth(), getProject()]);
        if (active && health.status === "ok") {
          setConnection("connected");
          setProject(projectInfo);
          try {
            setProjectTree(await getProjectTree());
          } catch (error) {
            setWorkspaceError(errorMessage(error, "无法读取项目文件"));
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

  const resetCompilation = useCallback(() => {
    setBrief(null);
    setCompilerKind(null);
    setCompilerNotice("");
    setCompileError("");
    setCompileState("idle");
  }, []);

  const updateNote = useCallback(
    (id: string, text: string, label: CanvasNoteLabel | null) => {
      setNodes((currentNodes) =>
        currentNodes.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, text, label } } : node,
        ),
      );
      resetCompilation();
    },
    [resetCompilation, setNodes],
  );

  const removeNote = useCallback(
    (id: string) => {
      setNodes((currentNodes) => currentNodes.filter((node) => node.id !== id));
      setEdges((currentEdges) =>
        currentEdges.filter((edge) => edge.source !== id && edge.target !== id),
      );
      resetCompilation();
    },
    [resetCompilation, setEdges, setNodes],
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
      resetCompilation();
    },
    [connectionLabel, resetCompilation, setEdges],
  );

  const handleNodesChange = useCallback(
    (changes: NodeChange<NoteNodeType>[]) => {
      onNodesChange(changes);
      if (nodeChangesInvalidateIntent(changes)) {
        resetCompilation();
      }
    },
    [onNodesChange, resetCompilation],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChange(changes);
      if (edgeChangesInvalidateIntent(changes)) {
        resetCompilation();
      }
    },
    [onEdgesChange, resetCompilation],
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
    resetCompilation();
  }

  function restoreExample() {
    setNodes(TODO_EXAMPLE_NODES.map((node) => ({ ...node, data: { ...node.data } })));
    setEdges(TODO_EXAMPLE_EDGES.map((edge) => ({ ...edge })));
    setSupplementalText("这个功能要适合两分钟内现场演示。");
    resetCompilation();
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

  async function handleCompile(compiler: CompilerKind = "ai") {
    setRun(null);
    setRunBrief(null);
    setRunError("");
    clearRunReview();
    setWorkspaceTab("canvas");
    setCompileState("compiling");
    setCompileError("");
    setBrief(null);
    setCompilerKind(null);
    setCompilerNotice("");
    try {
      const result = await compileIntent(
        toIntentCanvas(nodes, edges, supplementalText),
        compiler,
      );
      setBrief(result.brief);
      setCompilerKind(result.compiler);
      setCompilerNotice(result.notice);
      setCompileState("completed");
    } catch (error) {
      setCompileError(error instanceof Error ? error.message : "意图整理失败");
      setCompileState("failed");
    }
  }

  async function refreshRun(runId: string) {
    try {
      const snapshot = await getRun(runId);
      setRun(snapshot);
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

  async function handleRun() {
    if (!brief) return;
    setRunError("");
    closeRunStream.current?.();
    clearRunReview();
    try {
      const created = await createRun(brief);
      setRun(created);
      setRunBrief(brief);
      void loadRunFacts(created);
      closeRunStream.current = subscribeToRun(
        created.id,
        (event) => {
          setRun((current) =>
            current
              ? {
                  ...current,
                  events: current.events.some((item) => item.sequence === event.sequence)
                    ? current.events
                    : [...current.events, event],
                }
              : current,
          );
        },
        () => void refreshRun(created.id),
        () => void refreshRun(created.id),
      );
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Agent 启动失败");
    }
  }

  async function handleStop() {
    if (!run || run.status !== "running") return;
    try {
      await stopRun(run.id);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "停止 Agent 失败");
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
      setRun(await discardRun(run.id));
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
  const isRunning = run?.status === "running";
  const activePhaseCount = run ? (run.status === "running" ? 4 : 5) : brief ? 2 : 1;
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
    ? { pending: "待审查", accepted: "已接受", discarded: "已放弃" }[run.review_status]
    : "待运行";

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
          <button
            className="compile-button"
            type="button"
            disabled={compileState === "compiling" || connection !== "connected" || isRunning}
            onClick={() => void handleCompile("ai")}
          >
            {compileState === "compiling" ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}
            整理意图
          </button>
          {isRunning ? (
            <button className="stop-button" type="button" onClick={() => void handleStop()}>
              <Square size={13} fill="currentColor" />停止
            </button>
          ) : (
            <button
              className="run-button"
              type="button"
              disabled={!brief || connection !== "connected"}
              title={brief ? "在 Todo 临时副本中运行" : "请先整理意图"}
              onClick={() => void handleRun()}
            >
              <Play size={15} fill="currentColor" />运行 Agent
            </button>
          )}
        </div>
      </header>

      <section className="phase-strip" aria-label="核心工作流">
        {phases.map((phase, index) => (
          <div className={`phase-item ${index < activePhaseCount ? "phase-item--active" : ""}`} key={phase}>
            <span className="phase-number">0{index + 1}</span><span>{phase}</span>
            {index < phases.length - 1 && <ArrowRight size={14} aria-hidden="true" />}
          </div>
        ))}
      </section>

      <div
        className="workspace-grid"
        style={{ gridTemplateColumns: `240px minmax(520px, 1fr) ${conversationWidth}px` }}
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
                      onChange={(event) => {
                        setSupplementalText(event.target.value);
                        resetCompilation();
                      }}
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
                      onConnect={onConnect} onNodesChange={handleNodesChange}
                      onEdgesChange={handleEdgesChange}
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
            <div className="panel-heading">
              <span>{run ? "单轮协作记录" : "意图理解摘要"}</span>
              <span className={`run-state run-state--${run?.status ?? compileState}`}>
                {run
                  ? runStatusText
                  : compileState === "completed"
                    ? compilerKind === "ai"
                      ? "AI 已整理"
                      : "本地降级"
                    : compileState === "failed"
                      ? "失败"
                      : "待整理"}
              </span>
            </div>
            {run ? (
              runBrief && (
                <SingleRunConversation
                  brief={runBrief}
                  run={run}
                  runError={runError}
                  changes={changes}
                  reviewAction={reviewAction}
                  reviewError={reviewError}
                  onHighlightSources={highlightSources}
                  onOpenRelatedFile={(path) => void openRelatedFile(path)}
                  onAccept={() => void handleAccept()}
                  onDiscard={() => void handleDiscard()}
                />
              )
            ) : !brief ? (
              <div className="run-empty">
                <span className="run-empty-icon"><CircleDot size={18} /></span>
                <strong>{compileError || "尚未生成 Intent Brief"}</strong>
                <p>便签可以零散、孤立或互相矛盾。点击“整理意图”查看结构化结果。</p>
                {compileState === "failed" && (
                  <button
                    className="fallback-button"
                    type="button"
                    disabled={connection !== "connected" || isRunning}
                    onClick={() => void handleCompile("local")}
                  >
                    <RotateCcw size={13} />使用本地规则整理
                  </button>
                )}
                {runError && <p className="inline-error">{runError}</p>}
              </div>
            ) : (
              <div className="brief-content">
                <span className="eyebrow">INTENT BRIEF</span>
                {compilerNotice && <p className="compiler-notice">{compilerNotice}</p>}
                <h2>{brief.title}</h2>
                <p className="brief-goal">{brief.goal}</p>
                <div className="brief-section">
                  <span className="brief-section__title">需求 · {brief.requirements.length}</span>
                  {brief.requirements.map((requirement) => (
                    <button className="requirement-card" key={requirement.id} type="button" onClick={() => highlightSources(requirement.source_ids)}>
                      <span className="requirement-card__id">{requirement.id}</span>
                      <strong>{requirement.description}</strong>
                      {requirement.acceptance_criteria.map((criterion) => (
                        <small key={criterion}><Check size={11} /> {criterion}</small>
                      ))}
                      <em>点击定位 {requirement.source_ids.length} 张来源便签</em>
                    </button>
                  ))}
                </div>
                {brief.constraints.length > 0 && (
                  <div className="brief-section">
                    <span className="brief-section__title">约束</span>
                    <ul>{brief.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
                  </div>
                )}
              </div>
            )}
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
        <span className="statusbar-spacer" /><span>v0.5.0 · review control</span>
      </footer>
    </main>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
