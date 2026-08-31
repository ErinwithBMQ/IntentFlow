import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  Folder,
  FolderOpen,
} from "lucide-react";
import { useState } from "react";

import type { WorkspaceEntry, WorkspaceTree } from "../../services/api";
import { workspaceFileKey } from "./workspaceState";

type ProjectExplorerProps = {
  projectTree: WorkspaceTree | null;
  activeFileKey: string | null;
  error: string;
  onOpenFile: (path: string) => void;
};

export function ProjectExplorer({
  projectTree,
  activeFileKey,
  error,
  onOpenFile,
}: ProjectExplorerProps) {
  return (
    <aside className="file-panel">
      <div className="panel-heading">
        <span>项目文件</span>
        <span className="stage-label">可编辑</span>
      </div>
      <div className="file-panel__content">
        <p className="workspace-version-note">
          打开文本文件即可编辑；待审查期间的手动保存会并入当前 Run。
        </p>
        <WorkspaceRoot
          title="当前项目"
          meta="实时文件"
          tree={projectTree}
          defaultExpanded
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
  tree: WorkspaceTree | null;
  defaultExpanded: boolean;
  activeFileKey: string | null;
  onOpenFile: (path: string) => void;
};

function WorkspaceRoot({
  title,
  meta,
  tree,
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
          <FolderOpen size={13} />{title}
        </span>
        <small>{meta}</small>
      </button>
      {expanded && (tree ? (
        <div className="file-tree">
          {tree.entries.map((entry) => (
            <FileTreeEntry
              key={entry.path}
              entry={entry}
              depth={0}
              activeFileKey={activeFileKey}
              onOpenFile={onOpenFile}
            />
          ))}
          {tree.entries.length === 0 && <p className="file-tree__empty">工作区为空</p>}
          {tree.truncated && <p className="file-tree__notice">目录过大，仅显示前 2000 项</p>}
        </div>
      ) : (
        <p className="file-tree__empty">正在读取…</p>
      ))}
    </section>
  );
}

type FileTreeEntryProps = {
  entry: WorkspaceEntry;
  depth: number;
  activeFileKey: string | null;
  onOpenFile: (path: string) => void;
};

function FileTreeEntry({
  entry,
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
            depth={depth + 1}
            activeFileKey={activeFileKey}
            onOpenFile={onOpenFile}
          />
        ))}
      </div>
    );
  }

  const key = workspaceFileKey(entry.path);
  return (
    <button
      className={`file-tree__row file-tree__row--file ${activeFileKey === key ? "file-tree__row--active" : ""}`}
      type="button"
      style={{ paddingLeft: paddingLeft + 14 }}
      title={entry.path}
      onClick={() => onOpenFile(entry.path)}
    >
      <FileCode2 size={12} />
      <span>{entry.name}</span>
    </button>
  );
}
