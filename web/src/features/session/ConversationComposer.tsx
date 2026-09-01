import { CircleHelp, Paperclip, Send, ShieldCheck, Square, Workflow } from "lucide-react";
import type { KeyboardEvent } from "react";

import type { ApprovalMode } from "../../services/api";

type ConversationComposerProps = {
  value: string;
  approvalMode: ApprovalMode;
  attachCanvas: boolean;
  canvasPlanMode: boolean;
  sending: boolean;
  activityRunning: boolean;
  interrupting: boolean;
  pendingReviewNotice: string;
  error: string;
  onChange: (value: string) => void;
  onApprovalModeChange: (mode: ApprovalMode) => void;
  onAttachCanvasChange: (attached: boolean) => void;
  onCanvasPlanModeChange: (enabled: boolean) => void;
  onSubmit: () => void;
  onInterrupt: () => void;
};

export function ConversationComposer({
  value,
  approvalMode,
  attachCanvas,
  canvasPlanMode,
  sending,
  activityRunning,
  interrupting,
  error,
  onChange,
  onApprovalModeChange,
  onAttachCanvasChange,
  onCanvasPlanModeChange,
  onSubmit,
  onInterrupt,
}: ConversationComposerProps) {
  const canInterrupt = sending || activityRunning;
  const submitDisabled = canInterrupt || !value.trim();

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
        <div className="conversation-composer__actions">
          <div className="canvas-plan-control">
            <button
              className={`canvas-plan-toggle ${canvasPlanMode ? "canvas-plan-toggle--active" : ""}`}
              type="button"
              aria-pressed={canvasPlanMode}
              aria-describedby="canvas-plan-tooltip"
              disabled={sending}
              onClick={() => onCanvasPlanModeChange(!canvasPlanMode)}
            >
              <Workflow size={13} />规划 Canvas 模式
            </button>
            <span
              className="canvas-plan-help"
              role="img"
              tabIndex={0}
              aria-label="规划 Canvas 模式说明"
            >
              <CircleHelp size={13} />
              <span id="canvas-plan-tooltip" className="canvas-plan-tooltip" role="tooltip">
                开启后，Agent 在执行任务前会先为你进行规划，并绘制出相应的 Canvas 面板。
                关闭时，对话内容不会触发 Canvas 规划。
              </span>
            </span>
          </div>
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
      </div>
      {error && <p className="conversation-composer__error">{error}</p>}
    </div>
  );
}
