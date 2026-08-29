import { Paperclip, Send } from "lucide-react";
import type { KeyboardEvent } from "react";

import type { ConversationMode } from "../../services/api";

type ConversationComposerProps = {
  value: string;
  mode: ConversationMode;
  attachCanvas: boolean;
  sending: boolean;
  agentBlocked: boolean;
  agentBlockReason: string;
  error: string;
  onChange: (value: string) => void;
  onModeChange: (mode: ConversationMode) => void;
  onAttachCanvasChange: (attached: boolean) => void;
  onSubmit: () => void;
};

const modeLabels: Record<ConversationMode, string> = {
  ask: "Ask",
  plan: "Plan",
  agent: "Agent",
};

const modeDescriptions: Record<ConversationMode, string> = {
  ask: "只读查看项目并回答，不修改或运行",
  plan: "只读查看项目并整理方案，不修改",
  agent: "以当前消息为主，按需参考附件并执行",
};

export function ConversationComposer({
  value,
  mode,
  attachCanvas,
  sending,
  agentBlocked,
  agentBlockReason,
  error,
  onChange,
  onModeChange,
  onAttachCanvasChange,
  onSubmit,
}: ConversationComposerProps) {
  const submitDisabled = sending || !value.trim() || (mode === "agent" && agentBlocked);

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
        <div className="conversation-mode" aria-label="对话模式">
          {(Object.keys(modeLabels) as ConversationMode[]).map((item) => (
            <button
              className={item === mode ? "conversation-mode--active" : ""}
              type="button"
              key={item}
              title={modeDescriptions[item]}
              disabled={sending}
              onClick={() => onModeChange(item)}
            >
              {modeLabels[item]}
            </button>
          ))}
        </div>
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
          className="conversation-send"
          type="button"
          disabled={submitDisabled}
          title={mode === "agent" && agentBlocked ? agentBlockReason : "发送"}
          onClick={onSubmit}
        >
          <Send size={14} />
        </button>
      </div>
      <div className="conversation-composer__hint">
        <span>
          {sending
            ? "正在处理消息…"
            : mode === "agent" && agentBlocked
              ? agentBlockReason
              : modeDescriptions[mode]}
        </span>
        <span>Enter 发送 · Shift+Enter 换行</span>
      </div>
      {error && <p className="conversation-composer__error">{error}</p>}
    </div>
  );
}
