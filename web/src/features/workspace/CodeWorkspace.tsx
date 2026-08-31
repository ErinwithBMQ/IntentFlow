import { FileCode2, LoaderCircle, X } from "lucide-react";
import { Fragment, useRef, type KeyboardEvent, type UIEvent } from "react";

import type { WorkspaceFile } from "../../services/api";
import { SyntaxLine } from "./SyntaxLine";

export type OpenWorkspaceFile = {
  key: string;
  path: string;
  state: "loading" | "ready" | "error";
  file: WorkspaceFile | null;
  draft: string;
  revision: number;
  saving: boolean;
  saveError: string;
  error: string;
};

type CodeWorkspaceProps = {
  files: OpenWorkspaceFile[];
  activeFileKey: string | null;
  editable: boolean;
  onSelectFile: (key: string) => void;
  onCloseFile: (key: string) => void;
  onChangeFile: (key: string, content: string) => void;
};

export function CodeWorkspace({
  files,
  activeFileKey,
  editable,
  onSelectFile,
  onCloseFile,
  onChangeFile,
}: CodeWorkspaceProps) {
  const activeFile = files.find((file) => file.key === activeFileKey) ?? null;
  const highlightedCodeRef = useRef<HTMLPreElement>(null);
  const dirty = Boolean(
    activeFile?.file && activeFile.draft !== activeFile.file.content,
  );

  function handleEditorKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Tab" || !activeFile) return;
    event.preventDefault();
    const editor = event.currentTarget;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const nextValue = `${activeFile.draft.slice(0, start)}  ${activeFile.draft.slice(end)}`;
    onChangeFile(activeFile.key, nextValue);
    requestAnimationFrame(() => editor.setSelectionRange(start + 2, start + 2));
  }

  function handleEditorScroll(event: UIEvent<HTMLTextAreaElement>) {
    if (!highlightedCodeRef.current) return;
    highlightedCodeRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightedCodeRef.current.scrollLeft = event.currentTarget.scrollLeft;
  }

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
              {file.file && file.draft !== file.file.content ? " •" : ""}
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
          description="从左侧项目文件中选择一个文本文件。"
        />
      ) : activeFile.state === "loading" ? (
        <WorkspaceEmpty title="正在读取文件" description={activeFile.path} loading />
      ) : activeFile.state === "error" || !activeFile.file ? (
        <WorkspaceEmpty title="无法显示文件" description={activeFile.error} />
      ) : (
        <div className="code-document">
          <div className="document-meta">
            <span>
              {activeFile.saving
                ? "保存中…"
                : dirty
                  ? "等待自动保存…"
                  : "项目文件"}
            </span>
            <code>{activeFile.file.path}</code>
            <small>{activeFile.file.language} · {formatBytes(activeFile.file.size)}</small>
          </div>
          <div className="code-editor-shell">
            <pre ref={highlightedCodeRef} className="code-editor-highlight" aria-hidden="true">
              {activeFile.draft.split(/\r?\n/).map((line, index, lines) => (
                <Fragment key={`${index}-${line}`}>
                  <SyntaxLine text={line || " "} language={activeFile.file?.language ?? "text"} />
                  {index < lines.length - 1 ? "\n" : null}
                </Fragment>
              ))}
            </pre>
            <textarea
              className="code-editor"
              aria-label={`${activeFile.file.path} 编辑器`}
              value={activeFile.draft}
              readOnly={!editable}
              spellCheck={false}
              onChange={(event) => onChangeFile(activeFile.key, event.target.value)}
              onKeyDown={handleEditorKeyDown}
              onScroll={handleEditorScroll}
            />
          </div>
          {activeFile.saveError && (
            <p className="code-editor-error">{activeFile.saveError}</p>
          )}
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
