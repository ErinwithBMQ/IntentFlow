import { ArrowRight, CircleDot, FileCode2, Play, Server, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { getHealth, getProject, type ProjectResponse } from "./services/api";

type ConnectionState = "checking" | "connected" | "failed";

const phases = ["表达想法", "整理意图", "修改代码", "运行验证"];

export function App() {
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [project, setProject] = useState<ProjectResponse | null>(null);

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
        if (active) {
          setConnection("failed");
        }
      }
    }

    void bootstrap();
    return () => {
      active = false;
    };
  }, []);

  const statusText = {
    checking: "正在连接后端",
    connected: "后端已连接",
    failed: "后端连接失败",
  }[connection];

  return (
    <main className="workspace-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            <Sparkles size={17} />
          </div>
          <span className="brand-name">IntentFlow</span>
          <span className="project-separator">/</span>
          <span className="project-name">{project?.name ?? "todo-demo"}</span>
        </div>

        <div className="topbar-actions">
          <div className={`connection-state connection-state--${connection}`}>
            <span className="connection-dot" aria-hidden="true" />
            {statusText}
          </div>
          <button className="run-button" type="button" disabled title="将在 Agent 阶段启用">
            <Play size={15} fill="currentColor" />
            运行 Agent
          </button>
        </div>
      </header>

      <section className="phase-strip" aria-label="核心工作流">
        {phases.map((phase, index) => (
          <div className="phase-item" key={phase}>
            <span className="phase-number">0{index + 1}</span>
            <span>{phase}</span>
            {index < phases.length - 1 && <ArrowRight size={14} aria-hidden="true" />}
          </div>
        ))}
      </section>

      <div className="workspace-grid">
        <aside className="tool-panel">
          <div className="panel-heading">
            <span>表达工具</span>
            <span className="stage-label">阶段 0</span>
          </div>

          <button className="tool-row" type="button" disabled>
            <CircleDot size={16} />
            自由便签
          </button>
          <button className="tool-row" type="button" disabled>
            <FileCode2 size={16} />
            代码参考
          </button>

          <p className="panel-note">画布能力将在 Agent 内核验证后接入。</p>
        </aside>

        <section className="canvas-panel">
          <div className="canvas-grid" aria-hidden="true" />
          <div className="canvas-empty">
            <span className="eyebrow">RUNNABLE FOUNDATION</span>
            <h1>先让每一层可靠连接</h1>
            <p>当前工作台已经接入真实后端。下一阶段将从最小 Agent 循环开始。</p>
            <div className="foundation-status">
              <span className="foundation-icon">
                <Server size={17} />
              </span>
              <span>
                <strong>{statusText}</strong>
                <small>{project?.relativePath ?? "examples/todo-demo"}</small>
              </span>
            </div>
          </div>
        </section>

        <aside className="run-panel">
          <div className="panel-heading">
            <span>Agent Run</span>
            <span className="run-state">未启动</span>
          </div>
          <div className="run-empty">
            <span className="run-empty-icon">
              <Play size={18} />
            </span>
            <strong>暂无运行记录</strong>
            <p>后续每一步都会显示动作、原因、结果和证据。</p>
          </div>
        </aside>
      </div>

      <footer className="statusbar">
        <span>Intent Brief：尚未生成</span>
        <span className="statusbar-divider" />
        <span>Target：{project?.relativePath ?? "examples/todo-demo"}</span>
        <span className="statusbar-spacer" />
        <span>v0.1.0 · foundation</span>
      </footer>
    </main>
  );
}

