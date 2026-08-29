import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  Folder,
  FolderOpen,
  GitCompareArrows,
} from "lucide-react";
import { useState } from "react";

import type { WorkspaceEntry, WorkspaceScope, WorkspaceTree } from "../../services/api";
import { workspaceFileKey } from "./workspaceState";

type ProjectExplorerProps = {
  projectTree: WorkspaceTree | null;
  runTree: WorkspaceTree | null;
  runId: string | null;
  activeFileKey: string | null;
  error: string;
  onOpenFile: (scope: WorkspaceScope, path: string) => void;
};

export function ProjectExplorer({
  projectTree,
  runTree,
  runId,
  activeFileKey,
  error,
  onOpenFile,
}: ProjectExplorerProps) {
  return (
    <aside className="file-panel">
      <div className="panel-heading">
        <span>项目文件</span>
        <span className="stage-label">只读</span>
      </div>
      <div className="file-panel__content">
        <p className="workspace-version-note">
          Agent 只修改隔离版本；点击“接受全部”后，变更才会写入项目当前版本。
        </p>
        <WorkspaceRoot
          key={`project-${runId ? "run" : "idle"}`}
          title="项目当前版本"
          meta="正式文件"
          scope="project"
          tree={projectTree}
          available
          defaultExpanded={!runId}
          activeFileKey={activeFileKey}
          onOpenFile={onOpenFile}
        />
        <WorkspaceRoot
          key={`run-${runId ?? "idle"}`}
          title="Agent 修改版本"
          meta={runId ? "隔离副本" : "等待运行"}
          scope="run"
          tree={runTree}
          available={Boolean(runId)}
          defaultExpanded={Boolean(runId)}
          activeFileKey={activeFileKey}
          onOpenFile={onOpenFile}
        />
        {error && <p className="file-panel__error">{error}</p>}
      </div>
    </aside>
  );
}

type WorkspaceRootProps = {
  title: string;
  meta: string;
  scope: WorkspaceScope;
  tree: WorkspaceTree | null;
  available: boolean;
  defaultExpanded: boolean;
  activeFileKey: string | null;
  onOpenFile: (scope: WorkspaceScope, path: string) => void;
};

function WorkspaceRoot({
  title,
  meta,
  scope,
  tree,
  available,
  defaultExpanded,
  activeFileKey,
  onOpenFile,
}: WorkspaceRootProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <section className="workspace-root">
      <button
        className="workspace-root__heading"
        type="button"
        onClick={() => setExpanded((current) => !current)}
      >
        <span>
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <GitCompareArrows size={13} />{title}
        </span>
        <small>{meta}</small>
      </button>
      {expanded && (tree ? (
        <div className="file-tree">
          {tree.entries.map((entry) => (
            <FileTreeEntry
              key={entry.path}
              entry={entry}
              scope={scope}
              depth={0}
              activeFileKey={activeFileKey}
              onOpenFile={onOpenFile}
            />
          ))}
          {tree.entries.length === 0 && <p className="file-tree__empty">工作区为空</p>}
          {tree.truncated && <p className="file-tree__notice">目录过大，仅显示前 2000 项</p>}
        </div>
      ) : (
        <p className="file-tree__empty">{available ? "正在读取…" : "运行后显示 Agent 修改版本"}</p>
      ))}
    </section>
  );
}

type FileTreeEntryProps = {
  entry: WorkspaceEntry;
  scope: WorkspaceScope;
  depth: number;
  activeFileKey: string | null;
  onOpenFile: (scope: WorkspaceScope, path: string) => void;
};

function FileTreeEntry({
  entry,
  scope,
  depth,
  activeFileKey,
  onOpenFile,
}: FileTreeEntryProps) {
  const [expanded, setExpanded] = useState(depth < 1);
  const paddingLeft = 10 + depth * 14;
  if (entry.kind === "directory") {
    return (
      <div>
        <button
          className="file-tree__row file-tree__row--directory"
          type="button"
          style={{ paddingLeft }}
          title={entry.path}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {expanded ? <FolderOpen size={13} /> : <Folder size={13} />}
          <span>{entry.name}</span>
        </button>
        {expanded && entry.children.map((child) => (
          <FileTreeEntry
            key={child.path}
            entry={child}
            scope={scope}
            depth={depth + 1}
            activeFileKey={activeFileKey}
            onOpenFile={onOpenFile}
          />
        ))}
      </div>
    );
  }

  const key = workspaceFileKey(scope, entry.path);
  return (
    <button
      className={`file-tree__row file-tree__row--file ${activeFileKey === key ? "file-tree__row--active" : ""}`}
      type="button"
      style={{ paddingLeft: paddingLeft + 14 }}
      title={entry.path}
      onClick={() => onOpenFile(scope, entry.path)}
    >
      <FileCode2 size={12} />
      <span>{entry.name}</span>
    </button>
  );
}
