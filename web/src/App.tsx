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
  Link2,
  LoaderCircle,
  Play,
  Plus,
  RotateCcw,
  Sparkles,
  Square,
  TerminalSquare,
  X,
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
import {
  compileIntent,
  createRun,
  getHealth,
  getProject,
  getRun,
  stopRun,
  subscribeToRun,
  type CanvasNoteLabel,
  type IntentBrief,
  type ProjectResponse,
  type RunEvent,
  type RunSnapshot,
} from "./services/api";

type ConnectionState = "checking" | "connected" | "failed";
type CompileState = "idle" | "compiling" | "completed" | "failed";
type CompilerKind = "ai" | "local";

const phases = ["表达想法", "整理意图", "修改代码", "运行验证"];
const STORAGE_KEY = "intentflow.canvas.v1";
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
  const [runError, setRunError] = useState("");
  const closeRunStream = useRef<(() => void) | null>(null);

  useEffect(() => {
    let active = true;
    async function bootstrap() {
      try {
        const [health, projectInfo] = await Promise.all([getHealth(), getProject()]);
        if (active && health.status === "ok") {
          setConnection("connected");
          setProject(projectInfo);
        }
      } catch {
        if (active) setConnection("failed");
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

  useEffect(() => () => closeRunStream.current?.(), []);

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
      if (changes.some((change) => change.type === "remove" || change.type === "position")) {
        resetCompilation();
      }
    },
    [onNodesChange, resetCompilation],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChange(changes);
      if (changes.some((change) => change.type === "remove")) {
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

  async function handleCompile(compiler: CompilerKind = "ai") {
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
      setRun(await getRun(runId));
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "无法读取运行结果");
    }
  }

  async function handleRun() {
    if (!brief) return;
    setRunError("");
    closeRunStream.current?.();
    try {
      const created = await createRun(brief);
      setRun(created);
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

  function highlightSources(sourceIds: string[]) {
    setNodes((currentNodes) =>
      currentNodes.map((node) => ({ ...node, selected: sourceIds.includes(node.id) })),
    );
  }

  const statusText = {
    checking: "正在连接后端",
    connected: "后端已连接",
    failed: "后端连接失败",
  }[connection];
  const isRunning = run?.status === "running";
  const activePhaseCount = isRunning ? 4 : brief ? 2 : 1;
  const runStatusText = run
    ? { running: "运行中", completed: "已完成", failed: "失败", stopped: "已停止" }[run.status]
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

      <div className="workspace-grid">
        <aside className="tool-panel">
          <div className="panel-heading"><span>表达工具</span><span className="stage-label">自由输入</span></div>
          <button className="tool-row tool-row--primary" type="button" onClick={addNote}>
            <Plus size={16} />添加便签
          </button>
          <button className="tool-row" type="button" onClick={restoreExample}>
            <RotateCcw size={15} />恢复 Todo 示例
          </button>
          <label className="tool-field">
            <span><Link2 size={13} /> 新连线文字</span>
            <input value={connectionLabel} placeholder="例如：然后、参考" onChange={(event) => setConnectionLabel(event.target.value)} />
          </label>
          <label className="tool-field tool-field--grow">
            <span>补充说明</span>
            <textarea
              value={supplementalText}
              placeholder="还有一些不好放进便签的话……"
              onChange={(event) => {
                setSupplementalText(event.target.value);
                resetCompilation();
              }}
            />
          </label>
          <p className="panel-note">标签、连线和顺序都不是必填。先把想法放上来，结构交给 AI。</p>
        </aside>

        <section className="canvas-panel">
          <div className="canvas-header">
            <span>Intent Canvas</span><span>{nodes.length} 张便签 · {edges.length} 条关系 · 已自动保存</span>
          </div>
          <NoteNodeProvider callbacks={callbacks}>
            <ReactFlow<NoteNodeType>
              fitView nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.55} maxZoom={1.45}
              onConnect={onConnect} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange}
            >
              <Background color="#d6d5cf" gap={20} size={1} variant={BackgroundVariant.Dots} />
            </ReactFlow>
          </NoteNodeProvider>
        </section>

        <aside className="run-panel intent-panel">
          <div className="panel-heading">
            <span>{run ? "Agent 运行轨迹" : "意图理解摘要"}</span>
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
            <div className="timeline-content">
              <div className="run-summary">
                <span className="eyebrow">RUN {run.id}</span>
                <strong>{brief?.title}</strong>
                <small><FileCode2 size={12} /> {run.workspace_relative_path}</small>
              </div>
              {runError && <p className="run-error"><X size={13} />{runError}</p>}
              <div className="timeline">
                {run.events.length === 0 && (
                  <div className="timeline-waiting"><LoaderCircle className="spin" size={15} />正在等待第一个动作…</div>
                )}
                {run.events.map((event) => <RunEventItem event={event} key={event.sequence} />)}
              </div>
              {run.report && (
                <div className={`final-report final-report--${run.status}`}>
                  <span>最终报告</span>
                  <strong>{run.report.summary}</strong>
                  {run.report.evidence.map((item) => <small key={item}><Check size={12} />{item}</small>)}
                  {run.report.unresolved.map((item) => <small key={item}><X size={12} />{item}</small>)}
                </div>
              )}
            </div>
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

      <footer className="statusbar">
        <span>Intent Brief：{brief ? `${brief.requirements.length} 项需求` : "尚未生成"}</span>
        <span className="statusbar-divider" />
        <span>Target：{run?.workspace_relative_path ?? project?.relativePath ?? "examples/todo-demo"}</span>
        <span className="statusbar-spacer" /><span>v0.3.0 · agent runtime</span>
      </footer>
    </main>
  );
}

function RunEventItem({ event }: { event: RunEvent }) {
  const isCommand = event.tool_name === "run_command";
  return (
    <article className={`timeline-event timeline-event--${event.status}`}>
      <div className="timeline-event__marker">
        {event.status === "running" ? (
          <LoaderCircle className="spin" size={13} />
        ) : event.status === "succeeded" ? (
          <Check size={13} />
        ) : (
          <X size={13} />
        )}
      </div>
      <div className="timeline-event__body">
        <span className="timeline-event__meta">#{event.sequence.toString().padStart(2, "0")} · {event.phase}</span>
        <strong>{event.action}</strong>
        <p>{event.reason}</p>
        {(event.tool_name || event.target) && (
          <code>{isCommand ? <TerminalSquare size={11} /> : <FileCode2 size={11} />}{event.tool_name}{event.target ? ` · ${event.target}` : ""}</code>
        )}
        {event.related_requirement_ids.length > 0 && (
          <small>关联 {event.related_requirement_ids.join("、")}</small>
        )}
        {event.evidence.map((item) => <small className="event-evidence" key={item}><Check size={10} />{item}</small>)}
      </div>
    </article>
  );
}
