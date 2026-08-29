import { FileCode2, LoaderCircle, X } from "lucide-react";

import type { WorkspaceFile, WorkspaceScope } from "../../services/api";
import { SyntaxLine } from "./SyntaxLine";

export type OpenWorkspaceFile = {
  key: string;
  scope: WorkspaceScope;
  path: string;
  state: "loading" | "ready" | "error";
  file: WorkspaceFile | null;
  error: string;
};

type CodeWorkspaceProps = {
  files: OpenWorkspaceFile[];
  activeFileKey: string | null;
  onSelectFile: (key: string) => void;
  onCloseFile: (key: string) => void;
};

export function CodeWorkspace({
  files,
  activeFileKey,
  onSelectFile,
  onCloseFile,
}: CodeWorkspaceProps) {
  const activeFile = files.find((file) => file.key === activeFileKey) ?? null;
  return (
    <div className="code-workspace">
      <div className="file-tabs" role="tablist" aria-label="已打开文件">
        {files.map((file) => (
          <div
            className={`file-tab ${file.key === activeFileKey ? "file-tab--active" : ""}`}
            key={file.key}
          >
            <button type="button" role="tab" onClick={() => onSelectFile(file.key)}>
              <FileCode2 size={11} />{file.path.split("/").pop()}
            </button>
            <button
              className="file-tab__close"
              type="button"
              title={`关闭 ${file.path}`}
              aria-label={`关闭 ${file.path}`}
              onClick={() => onCloseFile(file.key)}
            >
              <X size={10} />
            </button>
          </div>
        ))}
      </div>
      {!activeFile ? (
        <WorkspaceEmpty
          title="尚未打开文件"
          description="从左侧项目当前版本或 Agent 修改版本中选择一个文本文件。"
        />
      ) : activeFile.state === "loading" ? (
        <WorkspaceEmpty title="正在读取文件" description={activeFile.path} loading />
      ) : activeFile.state === "error" || !activeFile.file ? (
        <WorkspaceEmpty title="无法显示文件" description={activeFile.error} />
      ) : (
        <div className="code-document">
          <div className="document-meta">
            <span>{activeFile.scope === "project" ? "项目当前版本" : "Agent 修改版本"}</span>
            <code>{activeFile.file.path}</code>
            <small>{activeFile.file.language} · {formatBytes(activeFile.file.size)}</small>
          </div>
          <div className="code-lines" aria-label={activeFile.file.path}>
            {activeFile.file.content.split(/\r?\n/).map((line, index) => (
              <div className="code-line" key={`${index}-${line}`}>
                <span>{index + 1}</span>
                <code><SyntaxLine text={line || " "} language={activeFile.file?.language ?? "text"} /></code>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

type WorkspaceEmptyProps = {
  title: string;
  description: string;
  loading?: boolean;
};

function WorkspaceEmpty({ title, description, loading = false }: WorkspaceEmptyProps) {
  return (
    <div className="workspace-empty">
      {loading ? <LoaderCircle className="spin" size={18} /> : <FileCode2 size={18} />}
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  return `${(size / 1024).toFixed(1)} KB`;
}
