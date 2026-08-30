import { Bot, CheckSquare, LoaderCircle, Paperclip, Sparkles, UserRound } from "lucide-react";
import { Fragment, Suspense, lazy, type ReactNode } from "react";

import type {
  ConversationMessage,
  RunSnapshot,
} from "../../services/api";

const MarkdownContent = lazy(() => import("./MarkdownContent").then(
  (module) => ({ default: module.MarkdownContent }),
));

type SessionConversationProps = {
  messages: ConversationMessage[];
  runs: RunSnapshot[];
  selectedRunId: string | null;
  selectedRunDetail: ReactNode;
  responding: boolean;
  onSelectRun: (run: RunSnapshot) => void;
};

const runStatusLabels: Record<RunSnapshot["status"], string> = {
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  stopped: "已停止",
};

export function SessionConversation({
  messages,
  runs,
  selectedRunId,
  selectedRunDetail,
  responding,
  onSelectRun,
}: SessionConversationProps) {
  const runById = new Map(runs.map((run) => [run.id, run]));

  if (messages.length === 0) {
    return (
      <div className="session-empty">
        <Bot size={22} />
        <strong>开始一段对话</strong>
        <p>直接描述需求，或附加当前 Canvas 后发送。</p>
      </div>
    );
  }

  return (
    <div className="session-conversation">
      {messages.map((message) => {
        const linkedRun = message.run_id ? runById.get(message.run_id) : null;
        return (
          <Fragment key={message.id}>
            <section className={`session-message session-message--${message.role}`}>
              <div className="conversation-avatar">
                {message.role === "user" ? <UserRound size={14} /> : <Sparkles size={14} />}
              </div>
              <div className="session-message__bubble">
                <div className="session-message__meta">
                  <span>{message.role === "user" ? "你" : "IntentFlow"}</span>
                </div>
                {message.role === "assistant" ? (
                  <div className="session-message__markdown">
                    <Suspense fallback={<p>{message.content}</p>}>
                      <MarkdownContent>{message.content}</MarkdownContent>
                    </Suspense>
                  </div>
                ) : (
                  <p>{message.content}</p>
                )}
                {message.intent && (
                  <div className="session-intent-brief">
                    <strong>{message.intent.title}</strong>
                    <span>{message.intent.goal}</span>
                    <ul>
                      {message.intent.requirements.map((requirement) => (
                        <li key={requirement.id}>
                          <b>{requirement.id}</b>{requirement.description}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {message.canvas_snapshot_id && (
                  <small className="session-message__attachment">
                    <Paperclip size={11} />已附加 Canvas 快照
                  </small>
                )}
                {linkedRun && linkedRun.id !== selectedRunId && (
                  <button
                    className="session-run-link"
                    type="button"
                    onClick={() => onSelectRun(linkedRun)}
                  >
                    <CheckSquare size={12} />查看运行 · {runStatusLabels[linkedRun.status]}
                  </button>
                )}
              </div>
            </section>
            {message.role === "assistant" && linkedRun?.id === selectedRunId
              ? selectedRunDetail
              : null}
          </Fragment>
        );
      })}
      {responding && (
        <section className="session-message session-message--assistant session-message--pending">
          <div className="conversation-avatar">
            <Sparkles size={14} />
          </div>
          <div className="session-message__bubble" aria-live="polite">
            <div className="session-message__meta">
              <span>IntentFlow</span>
            </div>
            <p><LoaderCircle className="spin" size={13} />正在读取会话并判断下一步…</p>
          </div>
        </section>
      )}
    </div>
  );
}
