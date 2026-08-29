import {
  Check,
  ChevronDown,
  CircleDot,
  FileCode2,
  LoaderCircle,
  LocateFixed,
  Sparkles,
  TerminalSquare,
  UserRound,
  X,
} from "lucide-react";
import { useMemo } from "react";

import type { IntentBrief, RunEvent, RunSnapshot } from "../../services/api";
import { buildConversationActivities, type ConversationAction } from "./conversation";

type SingleRunConversationProps = {
  brief: IntentBrief;
  run: RunSnapshot;
  runError: string;
  onHighlightSources: (sourceIds: string[]) => void;
  onOpenRelatedFile: (path: string) => void;
};

const requirementStatusText = {
  verified: "已验证",
  implemented: "已实现",
  failed: "失败",
  unresolved: "未解决",
} as const;

export function SingleRunConversation({
  brief,
  run,
  runError,
  onHighlightSources,
  onOpenRelatedFile,
}: SingleRunConversationProps) {
  const activities = useMemo(() => buildConversationActivities(run.events), [run.events]);

  return (
    <div className="conversation-content">
      <div className="conversation-run-meta">
        <span>单次运行 · {run.id}</span>
        <small><FileCode2 size={11} />{run.workspace_relative_path}</small>
      </div>

      <section className="conversation-message conversation-message--user">
        <div className="conversation-avatar"><UserRound size={14} /></div>
        <div className="conversation-bubble">
          <span className="conversation-speaker">本轮目标</span>
          <strong>{brief.title}</strong>
          <p>{brief.goal}</p>
          <small>{brief.requirements.length} 项需求 · {brief.constraints.length} 项约束</small>
        </div>
      </section>

      <section className="conversation-message conversation-message--agent">
        <div className="conversation-avatar"><Sparkles size={14} /></div>
        <div className="conversation-bubble">
          <span className="conversation-speaker">Agent 理解</span>
          <strong>我会按本轮冻结的 Intent Brief 实现并验证</strong>
          <div className="conversation-intent-list">
            {brief.requirements.map((requirement) => (
              <button
                type="button"
                key={requirement.id}
                onClick={() => onHighlightSources(requirement.source_ids)}
              >
                <span>{requirement.id}</span>{requirement.description}
              </button>
            ))}
          </div>
          {brief.constraints.length > 0 && (
            <details className="conversation-details">
              <summary>查看 {brief.constraints.length} 项约束</summary>
              <ul>{brief.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
            </details>
          )}
        </div>
      </section>

      {runError && <p className="run-error"><X size={13} />{runError}</p>}

      <section className="conversation-message conversation-message--agent">
        <div className="conversation-avatar"><Sparkles size={14} /></div>
        <div className="conversation-bubble conversation-bubble--progress">
          <span className="conversation-speaker">Agent 进展</span>
          {activities.length === 0 ? (
            <div className="conversation-waiting">
              <LoaderCircle className="spin" size={14} />正在等待第一个动作…
            </div>
          ) : (
            <div className="conversation-activities">
              {activities.map((activity) => (
                <article
                  className={`conversation-activity conversation-activity--${activity.status}`}
                  key={activity.id}
                >
                  <div className="conversation-activity__marker">
                    <StatusIcon status={activity.status} />
                  </div>
                  <div className="conversation-activity__body">
                    <strong>{activity.title}</strong>
                    {activity.actions.length === 0 ? (
                      <p>{activity.reason}</p>
                    ) : (
                      <details className="conversation-details">
                        <summary>
                          {activity.actions.length} 个动作
                          {activity.requirementIds.length > 0
                            ? ` · 关联 ${activity.requirementIds.join("、")}`
                            : ""}
                          <ChevronDown size={12} />
                        </summary>
                        <div className="conversation-action-list">
                          {activity.actions.map((action) => (
                            <ConversationActionItem
                              action={action}
                              key={action.id}
                              onOpenRelatedFile={onOpenRelatedFile}
                            />
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      {run.report && (
        <section className="conversation-message conversation-message--agent">
          <div className="conversation-avatar"><Sparkles size={14} /></div>
          <div className="conversation-bubble conversation-bubble--result">
            <span className="conversation-speaker">Agent 结果</span>
            <div className={`conversation-verdict conversation-verdict--${run.status}`}>
              <strong>{run.report.summary}</strong>
              {run.report.evidence.map((item) => (
                <small key={item}><Check size={11} />{item}</small>
              ))}
              {run.report.unresolved.map((item) => (
                <small className="conversation-unresolved" key={item}><X size={11} />{item}</small>
              ))}
            </div>

            <div className="requirement-results">
              <span className="requirement-results__title">逐需求结论</span>
              {run.report.requirement_results.map((result) => {
                const sourceIds = brief.requirements.find(
                  (requirement) => requirement.id === result.requirement_id,
                )?.source_ids ?? [];
                return (
                  <article className="requirement-result" key={result.requirement_id}>
                    <div className="requirement-result__heading">
                      <span>{result.requirement_id}</span>
                      <span className={`requirement-status requirement-status--${result.status}`}>
                        {requirementStatusText[result.status]}
                      </span>
                      <button
                        type="button"
                        title="定位来源便签"
                        aria-label={`定位 ${result.requirement_id} 的来源便签`}
                        disabled={sourceIds.length === 0}
                        onClick={() => onHighlightSources(sourceIds)}
                      >
                        <LocateFixed size={13} />
                      </button>
                    </div>
                    <p>{result.summary}</p>
                    {(result.related_files.length > 0 || result.evidence.length > 0) && (
                      <details className="conversation-details">
                        <summary>
                          {result.related_files.length} 个文件 · {result.evidence.length} 条证据
                          <ChevronDown size={12} />
                        </summary>
                        {result.related_files.map((file) => (
                          <button
                            className="related-file-link"
                            type="button"
                            key={file}
                            onClick={() => onOpenRelatedFile(file)}
                          >
                            <FileCode2 size={11} />{file}
                          </button>
                        ))}
                        {result.evidence.map((item) => (
                          <small key={item}><Check size={11} />{item}</small>
                        ))}
                      </details>
                    )}
                  </article>
                );
              })}
            </div>
          </div>
        </section>
      )}

      <RawEventDetails events={run.events} />
    </div>
  );
}

function ConversationActionItem({
  action,
  onOpenRelatedFile,
}: {
  action: ConversationAction;
  onOpenRelatedFile: (path: string) => void;
}) {
  const isCommand = action.toolName === "run_command";
  const isFile = action.toolName === "read_file" || action.toolName === "apply_patch";
  const target = action.target;
  return (
    <div className={`conversation-action conversation-action--${action.status}`}>
      <StatusIcon status={action.status} />
      <div>
        <strong>{action.action}</strong>
        {target && (isFile ? (
          <button
            className="conversation-file-link"
            type="button"
            onClick={() => onOpenRelatedFile(target)}
          >
            <FileCode2 size={10} />{target}
          </button>
        ) : (
          <code>
            {isCommand ? <TerminalSquare size={10} /> : <FileCode2 size={10} />}
            {target}
          </code>
        ))}
        {action.reason && <p>{action.reason}</p>}
        {action.evidence.map((item) => <small key={item}>{item}</small>)}
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: RunEvent["status"] }) {
  if (status === "running") return <LoaderCircle className="spin" size={12} />;
  if (status === "succeeded") return <Check size={12} />;
  if (status === "failed" || status === "stopped") return <X size={12} />;
  return <CircleDot size={12} />;
}

function RawEventDetails({ events }: { events: RunEvent[] }) {
  return (
    <details className="raw-events">
      <summary>查看原始运行记录 · {events.length} 条</summary>
      <div>
        {events.map((event) => (
          <article key={event.sequence}>
            <span>#{event.sequence.toString().padStart(2, "0")} · {event.kind}</span>
            <strong>{event.action}</strong>
            {event.target && <code>{event.target}</code>}
          </article>
        ))}
      </div>
    </details>
  );
}
