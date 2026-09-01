import { FolderOpen, Plus, Settings2, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { ProjectResponse, ProjectTemplate } from "../../services/api";

type ProjectDialogProps = {
  open: boolean;
  required: boolean;
  project: ProjectResponse | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onPickExisting: () => void;
  onPickParent: () => Promise<string | null>;
  onRegisterPath: (path: string) => void;
  onCreate: (parentPath: string, name: string, template: ProjectTemplate) => void;
  onSave: (project: ProjectResponse) => void;
};

type DialogTab = "existing" | "create" | "settings";

export function ProjectDialog({
  open,
  required,
  project,
  busy,
  error,
  onClose,
  onPickExisting,
  onPickParent,
  onRegisterPath,
  onCreate,
  onSave,
}: ProjectDialogProps) {
  const [tab, setTab] = useState<DialogTab>("existing");
  const [path, setPath] = useState("");
  const [parentPath, setParentPath] = useState("");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState<ProjectTemplate>("web");
  const [settingsName, setSettingsName] = useState("");
  const [testCommand, setTestCommand] = useState("");
  const [buildCommand, setBuildCommand] = useState("");
  const [ignoredNames, setIgnoredNames] = useState("");
  const [projectPrompt, setProjectPrompt] = useState("");

  useEffect(() => {
    if (!project) return;
    setSettingsName(project.name);
    setTestCommand(commandToText(project.test_command));
    setBuildCommand(commandToText(project.build_command));
    setIgnoredNames(project.ignored_names.join(", "));
    setProjectPrompt(project.prompt);
  }, [project]);

  if (!open) return null;

  async function chooseParent() {
    const selected = await onPickParent();
    if (selected) setParentPath(selected);
  }

  function saveSettings() {
    if (!project) return;
    onSave({
      ...project,
      name: settingsName.trim(),
      test_command: textToCommand(testCommand),
      build_command: textToCommand(buildCommand),
      ignored_names: ignoredNames.split(",").map((item) => item.trim()).filter(Boolean),
      prompt: projectPrompt.trim(),
    });
  }

  return (
    <div className="project-dialog-backdrop" role="presentation">
      <section className="project-dialog" role="dialog" aria-modal="true" aria-label="项目管理">
        <header>
          <div>
            <span>LOCAL WORKSPACE</span>
            <h2>{required ? "选择一个项目开始" : "项目管理"}</h2>
          </div>
          {!required && (
            <button type="button" aria-label="关闭项目管理" onClick={onClose}>
              <X size={17} />
            </button>
          )}
        </header>

        <nav aria-label="项目管理选项">
          <button
            className={tab === "existing" ? "project-dialog__tab--active" : ""}
            type="button"
            onClick={() => setTab("existing")}
          >
            添加已有项目
          </button>
          <button
            className={tab === "create" ? "project-dialog__tab--active" : ""}
            type="button"
            onClick={() => setTab("create")}
          >
            创建新项目
          </button>
          {project && (
            <button
              className={tab === "settings" ? "project-dialog__tab--active" : ""}
              type="button"
              onClick={() => setTab("settings")}
            >
              项目设置
            </button>
          )}
        </nav>

        {tab === "existing" && (
          <div className="project-dialog__body">
            <div className="project-dialog__hero">
              <FolderOpen size={30} />
              <div>
                <strong>打开本机项目文件夹</strong>
                <p>选择后只授权这个目录；Agent 经批准后会直接修改其中的项目文件。</p>
              </div>
            </div>
            <button className="project-dialog__primary" type="button" disabled={busy} onClick={onPickExisting}>
              <FolderOpen size={15} />打开文件夹选择器
            </button>
            <div className="project-dialog__divider"><span>或手动输入绝对路径</span></div>
            <label>
              项目路径
              <input
                value={path}
                placeholder="E:\\projects\\my-app"
                onChange={(event) => setPath(event.target.value)}
              />
            </label>
            <button
              className="project-dialog__secondary"
              type="button"
              disabled={busy || !path.trim()}
              onClick={() => onRegisterPath(path.trim())}
            >
              添加这个目录
            </button>
          </div>
        )}

        {tab === "create" && (
          <div className="project-dialog__body">
            <label>
              保存位置
              <div className="project-dialog__path-row">
                <input
                  value={parentPath}
                  placeholder="选择项目的父目录"
                  onChange={(event) => setParentPath(event.target.value)}
                />
                <button type="button" disabled={busy} onClick={() => void chooseParent()}>
                  浏览
                </button>
              </div>
            </label>
            <label>
              项目名称
              <input
                value={name}
                placeholder="my-project"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              项目模板
              <select value={template} onChange={(event) => setTemplate(event.target.value as ProjectTemplate)}>
                <option value="web">原生 Web 模板</option>
                <option value="empty">空项目</option>
              </select>
            </label>
            <button
              className="project-dialog__primary"
              type="button"
              disabled={busy || !parentPath.trim() || !name.trim()}
              onClick={() => onCreate(parentPath.trim(), name.trim(), template)}
            >
              <Plus size={15} />创建并打开
            </button>
            <p className="project-dialog__note">创建项目不会自动安装依赖或运行命令。</p>
          </div>
        )}

        {tab === "settings" && project && (
          <div className="project-dialog__body">
            <label>
              显示名称
              <input value={settingsName} onChange={(event) => setSettingsName(event.target.value)} />
            </label>
            <label>
              项目 Prompt
              <textarea
                rows={5}
                maxLength={20000}
                value={projectPrompt}
                placeholder="例如：默认使用中文回复；修改前先阅读项目约定；保持现有代码风格。"
                onChange={(event) => setProjectPrompt(event.target.value)}
              />
            </label>
            <label>
              测试命令参数
              <textarea
                rows={3}
                value={testCommand}
                placeholder={"每行一个参数，例如：\nnpm\ntest"}
                onChange={(event) => setTestCommand(event.target.value)}
              />
            </label>
            <label>
              构建命令参数
              <textarea
                rows={3}
                value={buildCommand}
                placeholder={"每行一个参数，例如：\nnpm\nrun\nbuild"}
                onChange={(event) => setBuildCommand(event.target.value)}
              />
            </label>
            <label>
              忽略目录（逗号分隔）
              <textarea
                rows={2}
                value={ignoredNames}
                onChange={(event) => setIgnoredNames(event.target.value)}
              />
            </label>
            <p className="project-dialog__note">
              命令按参数逐行保存，不经过 Shell；可使用 {"{workspace}"} 表示 Agent 隔离目录。
            </p>
            <button
              className="project-dialog__primary"
              type="button"
              disabled={busy || !settingsName.trim()}
              onClick={saveSettings}
            >
              <Settings2 size={15} />保存项目设置
            </button>
          </div>
        )}

        {error && <p className="project-dialog__error">{error}</p>}
      </section>
    </div>
  );
}

function commandToText(command: string[] | null): string {
  return command?.join("\n") ?? "";
}

function textToCommand(value: string): string[] | null {
  const command = value.split("\n").map((item) => item.trim()).filter(Boolean);
  return command.length > 0 ? command : null;
}
