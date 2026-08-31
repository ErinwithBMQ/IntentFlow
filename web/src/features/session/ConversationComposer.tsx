import { Paperclip, Send, ShieldCheck, Square } from "lucide-react";
import type { KeyboardEvent } from "react";

import type { ApprovalMode } from "../../services/api";

type ConversationComposerProps = {
  value: string;
  approvalMode: ApprovalMode;
  attachCanvas: boolean;
  sending: boolean;
  activityRunning: boolean;
  interrupting: boolean;
  pendingReviewNotice: string;
  error: string;
  onChange: (value: string) => void;
  onApprovalModeChange: (mode: ApprovalMode) => void;
  onAttachCanvasChange: (attached: boolean) => void;
  onSubmit: () => void;
  onInterrupt: () => void;
};

const approvalDescriptions: Record<ApprovalMode, string> = {
  ask: "修改前请求批准",
  auto: "自动允许受控修改，完成后仍可撤销",
};

export function ConversationComposer({
  value,
  approvalMode,
  attachCanvas,
  sending,
  activityRunning,
  interrupting,
  pendingReviewNotice,
  error,
  onChange,
  onApprovalModeChange,
  onAttachCanvasChange,
  onSubmit,
  onInterrupt,
}: ConversationComposerProps) {
  const canInterrupt = sending || activityRunning;
  const submitDisabled = canInterrupt || !value.trim();
  const hint = interrupting
    ? "正在中断当前处理…"
    : sending
      ? "Agent 正在读取会话并判断下一步…"
      : activityRunning
        ? "Agent 正在执行，点击右侧方形按钮可中断"
        : pendingReviewNotice || approvalDescriptions[approvalMode];

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!submitDisabled) onSubmit();
    }
  }

  return (
    <div className="conversation-composer">
      <textarea
        value={value}
        rows={3}
        placeholder="描述问题、补充要求，或让 Agent 修改代码……"
        aria-label="发送消息"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="conversation-composer__toolbar">
        <label className="permission-mode">
          <ShieldCheck size={12} />
          <span>权限</span>
          <select
            aria-label="Agent 权限"
            value={approvalMode}
            disabled={sending}
            onChange={(event) => onApprovalModeChange(event.target.value as ApprovalMode)}
          >
            <option value="ask">请求批准</option>
            <option value="auto">自动允许</option>
          </select>
        </label>
        <label className="canvas-attachment-toggle" title="发送时保存当前 Canvas 的不可变快照">
          <input
            type="checkbox"
            checked={attachCanvas}
            disabled={sending}
            onChange={(event) => onAttachCanvasChange(event.target.checked)}
          />
          <Paperclip size={13} />Canvas
        </label>
        <button
          className={`conversation-send ${canInterrupt ? "conversation-send--interrupt" : ""}`}
          type="button"
          disabled={canInterrupt ? interrupting : submitDisabled}
          title={canInterrupt ? "中断当前处理" : "发送"}
          aria-label={canInterrupt ? "中断当前处理" : "发送"}
          onClick={canInterrupt ? onInterrupt : onSubmit}
        >
          {canInterrupt ? <Square size={13} fill="currentColor" /> : <Send size={14} />}
        </button>
      </div>
      <div className="conversation-composer__hint">
        <span>{hint}</span>
        <span>Enter 发送 · Shift+Enter 换行</span>
      </div>
      {error && <p className="conversation-composer__error">{error}</p>}
    </div>
  );
}
