import { FileDiff as FileDiffIcon, LoaderCircle } from "lucide-react";

import type { ChangeSummary, FileChange, FileDiff } from "../../services/api";
import { SyntaxLine } from "./SyntaxLine";
import { diffLineKind, languageFromPath } from "./workspaceState";

type DiffWorkspaceProps = {
  changes: ChangeSummary | null;
  activePath: string | null;
  diff: FileDiff | null;
  loading: boolean;
  error: string;
  onSelectChange: (change: FileChange) => void;
};

const changeLabels = {
  added: "新增",
  modified: "修改",
  deleted: "删除",
} as const;

const unavailableLabels = {
  binary: "二进制文件不提供文本 Diff",
  invalid_utf8: "文件不是有效的 UTF-8 文本",
  too_large: "文件超过可查看大小限制",
} as const;

export function DiffWorkspace({
  changes,
  activePath,
  diff,
  loading,
  error,
  onSelectChange,
}: DiffWorkspaceProps) {
  if (!changes) {
    return (
      <WorkspaceDiffEmpty
        title="尚无正式 Diff"
        description="Agent 运行进入终态后，这里会显示真实文件比较结果。"
      />
    );
  }
  if (changes.changed_files === 0) {
    return (
      <WorkspaceDiffEmpty
        title="本次运行未产生文件变更"
        description="验证结果与代码变更是独立状态；本轮没有可审查的文件差异。"
      />
    );
  }

  const activeChange = changes.files.find((change) => change.path === activePath) ?? null;
  return (
    <div className="diff-workspace">
      <aside className="change-list">
        <div className="change-summary">
          <strong>{changes.changed_files} 个变更文件</strong>
          <span><b>+{changes.additions}</b><em>-{changes.deletions}</em></span>
        </div>
        {changes.files.map((change) => (
          <button
            className={`change-row ${change.path === activePath ? "change-row--active" : ""}`}
            type="button"
            key={change.path}
            title={change.path}
            onClick={() => onSelectChange(change)}
          >
            <span className={`change-kind change-kind--${change.status}`}>
              {changeLabels[change.status]}
            </span>
            <code>{change.path}</code>
            <small><b>+{change.additions}</b><em>-{change.deletions}</em></small>
          </button>
        ))}
      </aside>
      <section className="diff-document">
        {!activeChange ? (
          <WorkspaceDiffEmpty title="选择变更文件" description="从左侧变更摘要中打开一个文件。" />
        ) : !activeChange.viewable ? (
          <WorkspaceDiffEmpty
            title="无法显示文本 Diff"
            description={activeChange.unavailable_reason
              ? unavailableLabels[activeChange.unavailable_reason]
              : "该文件不支持文本预览"}
          />
        ) : loading ? (
          <WorkspaceDiffEmpty title="正在生成 Diff" description={activeChange.path} loading />
        ) : error ? (
          <WorkspaceDiffEmpty title="无法读取 Diff" description={error} />
        ) : diff ? (
          <>
            <div className="document-meta">
              <span>{changeLabels[diff.status]}</span>
              <code>{diff.path}</code>
              <small><b>+{diff.additions}</b> <em>-{diff.deletions}</em></small>
            </div>
            <div className="diff-lines" aria-label={`${diff.path} Diff`}>
              {diff.diff.split(/\r?\n/).filter((line, index, lines) => (
                line.length > 0 || index < lines.length - 1
              )).map((line, index) => {
                const kind = diffLineKind(line);
                const hasCodeBody = kind === "addition" || kind === "deletion" || kind === "context";
                return (
                  <div className={`diff-line diff-line--${kind}`} key={`${index}-${line}`}>
                    <span>{index + 1}</span>
                    <code>
                      {hasCodeBody ? (
                        <>
                          <span className="diff-prefix">{line.slice(0, 1) || " "}</span>
                          <SyntaxLine text={line.slice(1)} language={languageFromPath(diff.path)} />
                        </>
                      ) : line || " "}
                    </code>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <WorkspaceDiffEmpty title="选择变更文件" description="打开一个文件查看真实 Diff。" />
        )}
      </section>
    </div>
  );
}

type WorkspaceDiffEmptyProps = {
  title: string;
  description: string;
  loading?: boolean;
};

function WorkspaceDiffEmpty({ title, description, loading = false }: WorkspaceDiffEmptyProps) {
  return (
    <div className="workspace-empty">
      {loading ? <LoaderCircle className="spin" size={18} /> : <FileDiffIcon size={18} />}
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}
