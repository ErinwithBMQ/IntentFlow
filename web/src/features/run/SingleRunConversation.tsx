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

import type {
  ApprovalDecision,
  ChangeSummary,
  IntentBrief,
  RunEvent,
  RunSnapshot,
} from "../../services/api";
import { SyntaxLine } from "../workspace/SyntaxLine";
import { diffLineKind, languageFromPath } from "../workspace/workspaceState";
import {
  buildConversationActivities,
  type ConversationAction,
  verificationStatusText,
} from "./conversation";

type SingleRunConversationProps = {
  brief: IntentBrief;
  run: RunSnapshot;
  runError: string;
  changes: ChangeSummary | null;
  reviewAction: "keep" | "undo" | null;
  toolApprovalAction: { approvalId: string; decision: ApprovalDecision } | null;
  reviewError: string;
  onHighlightSources: (sourceIds: string[]) => void;
  onOpenRelatedFile: (path: string) => void;
  onKeep: () => void;
  onUndo: () => void;
  onResolveApproval: (approvalId: string, decision: ApprovalDecision) => void;
  showIntentContext?: boolean;
};

const requirementStatusText = {
  verified: "已验证",
  implemented: "已实现",
  failed: "失败",
  unresolved: "未解决",
} as const;

const reviewStatusText = {
  pending: "待审查",
  accepted: "已保留",
  discarded: "已撤销",
} as const;

function approvalReasonText(reason: string, target: string | null) {
  if (/[\u3400-\u9fff]/u.test(reason)) return reason;
  return `Agent 准备修改 ${target ?? "当前文件"}，请检查下方具体差异。`;
}

export function SingleRunConversation({
  brief,
  run,
  runError,
  changes,
  reviewAction,
  toolApprovalAction,
  reviewError,
  onHighlightSources,
  onOpenRelatedFile,
  onKeep,
  onUndo,
  onResolveApproval,
  showIntentContext = true,
}: SingleRunConversationProps) {
  const activities = useMemo(() => buildConversationActivities(run.events), [run.events]);
  const activeAction = [...activities]
    .reverse()
    .flatMap((activity) => [...activity.actions].reverse())
    .find((action) => action.status === "running");
  const pendingApproval = run.approvals.find(
    (approval) => approval.status === "approval_required",
  ) ?? null;
  const hasVerification = (run.report?.evidence.length ?? 0) > 0;
  const completedRequirementCount = run.report?.requirement_results.filter(
    (result) => result.status === "verified" || result.status === "implemented",
  ).length ?? 0;
  const latestVerificationStatus = [...run.events]
    .reverse()
    .find((event) => event.tool_name === "run_command" && event.verification_status)
    ?.verification_status;

  return (
    <div className={`conversation-content ${showIntentContext ? "" : "conversation-content--embedded"}`}>
      {showIntentContext && (
        <>
          <div className="conversation-run-meta">
            <span>单次运行 · {run.id}</span>
            <small><FileCode2 size={11} />{run.project_name ?? "当前项目"}</small>
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
              <strong>接下来会处理：{brief.title}</strong>
              <details className="conversation-details intent-details">
                <summary>
                  查看任务详情 · {brief.requirements.length} 项
                  <ChevronDown size={12} />
                </summary>
                <p>{brief.goal}</p>
                <div className="conversation-intent-list">
                  {brief.requirements.map((requirement) => (
                    <button
                      type="button"
                      key={requirement.id}
                      onClick={() => onHighlightSources(requirement.source_ids)}
                    >
                      {requirement.description}
                    </button>
                  ))}
                </div>
                {brief.constraints.length > 0 && (
                  <ul>{brief.constraints.map((constraint) => <li key={constraint}>{constraint}</li>)}</ul>
                )}
              </details>
            </div>
          </section>
        </>
      )}

      {runError && <p className="run-error"><X size={13} />{runError}</p>}

      {pendingApproval && (
        <section className="conversation-message conversation-message--agent">
          <div className="conversation-avatar"><FileCode2 size={14} /></div>
          <div className="conversation-bubble approval-card">
            <div className="approval-card__heading">
              <span className="conversation-speaker">等待修改批准</span>
              <code>{pendingApproval.target ?? pendingApproval.tool_name}</code>
            </div>
            <strong>{approvalReasonText(pendingApproval.reason, pendingApproval.target)}</strong>
            <div
              className="diff-lines approval-patch"
              aria-label={`${pendingApproval.target ?? "文件"} 待审批 Diff`}
            >
              {pendingApproval.patch.split(/\r?\n/).filter((line, index, lines) => (
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
                          <SyntaxLine
                            text={line.slice(1)}
                            language={languageFromPath(pendingApproval.target ?? "")}
                          />
                        </>
                      ) : line || " "}
                    </code>
                  </div>
                );
              })}
            </div>
            <div className="approval-actions">
              <button
                type="button"
                className="review-button review-button--discard"
                disabled={toolApprovalAction !== null}
                onClick={() => onResolveApproval(pendingApproval.id, "reject")}
              >
                {toolApprovalAction?.approvalId === pendingApproval.id
                  && toolApprovalAction.decision === "reject"
                  && <LoaderCircle className="spin" size={12} />}
                拒绝
              </button>
              <button
                type="button"
                className="review-button"
                disabled={toolApprovalAction !== null}
                onClick={() => onResolveApproval(pendingApproval.id, "allow_once")}
              >
                {toolApprovalAction?.approvalId === pendingApproval.id
                  && toolApprovalAction.decision === "allow_once"
                  && <LoaderCircle className="spin" size={12} />}
                允许一次
              </button>
              <button
                type="button"
                className="review-button review-button--accept"
                disabled={toolApprovalAction !== null}
                onClick={() => onResolveApproval(pendingApproval.id, "allow_for_run")}
              >
                {toolApprovalAction?.approvalId === pendingApproval.id
                  && toolApprovalAction.decision === "allow_for_run" && (
                  <LoaderCircle className="spin" size={12} />
                )}
                本轮自动允许
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="conversation-message conversation-message--agent">
        <div className="conversation-avatar"><Sparkles size={14} /></div>
        <div className="conversation-bubble conversation-bubble--progress">
          <span className="conversation-speaker">Agent 进展</span>
          {activities.length > 0 && (
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
          {run.status === "running" && (
            <div className="conversation-live-status" role="status" aria-live="polite">
              <LoaderCircle className="spin" size={15} />
              <div>
                <strong>{pendingApproval ? "Agent 等待批准" : "Agent 运行中"}</strong>
                <span>
                  {pendingApproval
                    ? `需要确认对 ${pendingApproval.target ?? "文件"} 的修改`
                    : activeAction
                    ? `正在执行：${activeAction.action || activeAction.toolName || "工具调用"}`
                    : "正在思考下一步…"}
                </span>
              </div>
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
              <strong>{reportHeadline(run.report.status, brief.title)}</strong>
              <div className="result-overview" aria-label="运行结果概览">
                {run.report.requirement_results.length > 0 && (
                  <span>
                    {completedRequirementCount}/{run.report.requirement_results.length} 项完成
                  </span>
                )}
                <span>
                  {verificationOverview(run.report.evidence.length, latestVerificationStatus)}
                </span>
                {changes && <span>{changes.changed_files} 个文件变更</span>}
                {run.report.unresolved.length > 0 && (
                  <span className="result-overview__warning">
                    {run.report.unresolved.length} 项未解决
                  </span>
                )}
              </div>
              <details className="conversation-details report-summary-details">
                <summary>
                  查看完整总结
                  <ChevronDown size={12} />
                </summary>
                <p>{run.report.summary}</p>
                {run.report.unresolved.map((item) => (
                  <small className="conversation-unresolved" key={item}>
                    <X size={11} />{item}
                  </small>
                ))}
              </details>
            </div>

            {run.report.requirement_results.length > 0 && (
              <details className="requirement-results">
                <summary>
                  <span>查看需求与证据</span>
                  <small>
                    {completedRequirementCount}/{run.report.requirement_results.length}
                  </small>
                  <ChevronDown size={12} />
                </summary>
                <div>
                  {run.report.requirement_results.map((result) => {
                    const requirement = brief.requirements.find(
                      (item) => item.id === result.requirement_id,
                    );
                    const sourceIds = requirement?.source_ids ?? [];
                    return (
                      <article className="requirement-result" key={result.requirement_id}>
                        <div className="requirement-result__heading">
                          <strong>{requirement?.description ?? result.requirement_id}</strong>
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
              </details>
            )}
          </div>
        </section>
      )}

      {run.status !== "running" && (
        <section className="conversation-message conversation-message--agent">
          <div className="conversation-avatar"><Check size={14} /></div>
          <div className="conversation-bubble review-card">
            <div className="review-card__heading">
              <span className="conversation-speaker">代码审查</span>
              <span className={`review-status review-status--${run.review_status}`}>
                {reviewStatusText[run.review_status]}
              </span>
            </div>
            {run.review_status === "pending" ? (
              <>
                <strong>
                  {changes
                    ? `${changes.changed_files} 个文件等待你的决定`
                    : "正在准备变更摘要"}
                </strong>
                <p>
                  {run.status === "completed" && hasVerification
                    ? "修改已经写入当前项目。你可以保留结果，或根据 Checkpoint 撤销本轮修改。"
                    : run.status === "completed"
                      ? "实现已经结束，但没有自动化验证结果。请检查代码和 Diff，再决定保留或撤销。"
                      : "本次运行未正常完成，当前项目可能包含不完整修改。请检查 Diff 后决定保留或撤销。"}
                </p>
                <div className="review-actions">
                  <button
                    className="review-button review-button--discard"
                    type="button"
                    disabled={reviewAction !== null}
                    onClick={onUndo}
                  >
                    {reviewAction === "undo" && <LoaderCircle className="spin" size={12} />}
                    撤销本轮
                  </button>
                  <button
                    className="review-button review-button--accept"
                    type="button"
                    disabled={reviewAction !== null || changes === null}
                    onClick={onKeep}
                  >
                    {reviewAction === "keep" && <LoaderCircle className="spin" size={12} />}
                    {run.status === "completed" && hasVerification
                      ? "保留修改"
                      : "仍然保留修改"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <strong>
                  {run.review_status === "accepted"
                    ? "本次修改已保留"
                    : "本次修改已撤销"}
                </strong>
                <p>
                  {run.review_status === "accepted"
                    ? "当前项目保留 Agent 的修改，历史 Diff 可继续核对。"
                    : "当前项目已恢复到本轮修改前，历史 Diff 仍保留用于核对。"}
                </p>
              </>
            )}
            {reviewError && <p className="review-error"><X size={12} />{reviewError}</p>}
          </div>
        </section>
      )}

      <RawEventDetails events={run.events} />
    </div>
  );
}

function reportHeadline(status: "completed" | "partial" | "failed", title: string): string {
  if (status === "completed") return `已完成：${title}`;
  if (status === "partial") return `部分完成：${title}`;
  return `未完成：${title}`;
}

function verificationOverview(
  evidenceCount: number,
  latestStatus: RunEvent["verification_status"],
): string {
  if (evidenceCount > 0) return `${evidenceCount} 项验证通过`;
  if (latestStatus) return verificationStatusText[latestStatus];
  return "未自动验证";
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
        {action.verificationStatus && (
          <small>{verificationStatusText[action.verificationStatus]}</small>
        )}
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
