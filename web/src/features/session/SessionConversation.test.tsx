import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../services/api";
import { ConversationComposer } from "./ConversationComposer";
import { MarkdownContent } from "./MarkdownContent";
import { SessionConversation } from "./SessionConversation";

function assistantMessage(content: string): ConversationMessage {
  return {
    id: "message-1",
    session_id: "session-1",
    role: "assistant",
    mode: "ask",
    content,
    canvas_snapshot_id: null,
    run_id: null,
    intent: null,
    created_at: "2026-08-29T00:00:00Z",
    sequence: 1,
  };
}

describe("SessionConversation", () => {
  it("renders assistant Markdown without executing raw HTML", () => {
    const html = renderToStaticMarkup(
      <MarkdownContent>
        {"**重点**：使用 `src/main.js`。\n\n<script>alert(1)</script>"}
      </MarkdownContent>,
    );

    expect(html).toContain("<strong>重点</strong>");
    expect(html).toContain("<code>src/main.js</code>");
    expect(html).not.toContain("<script>");
  });

  it("shows a unified Agent response indicator", () => {
    const html = renderToStaticMarkup(
      <SessionConversation
        messages={[assistantMessage("上一条回复")]}
        runs={[]}
        selectedRunId={null}
        selectedRunDetail={null}
        responding
        onSelectRun={() => undefined}
      />,
    );

    expect(html).toContain("正在读取会话并判断下一步…");
    expect(html).not.toContain("Ask");
  });

  it("uses one Agent input with an independent approval selector", () => {
    const html = renderToStaticMarkup(
      <ConversationComposer
        value="解释上一轮结果"
        approvalMode="ask"
        attachCanvas={false}
        sending={false}
        activityRunning={false}
        interrupting={false}
        pendingReviewNotice="上一轮修改待审查，你仍可继续提问"
        error=""
        onChange={() => undefined}
        onApprovalModeChange={() => undefined}
        onAttachCanvasChange={() => undefined}
        onSubmit={() => undefined}
        onInterrupt={() => undefined}
      />,
    );

    expect(html).toContain("Agent 权限");
    expect(html).toContain("请求批准");
    expect(html).toContain("上一轮修改待审查，你仍可继续提问");
    expect(html).not.toContain(">Plan<");
  });

  it("replaces send with interrupt while the Agent is active", () => {
    const html = renderToStaticMarkup(
      <ConversationComposer
        value=""
        approvalMode="ask"
        attachCanvas={false}
        sending
        activityRunning={false}
        interrupting={false}
        pendingReviewNotice=""
        error=""
        onChange={() => undefined}
        onApprovalModeChange={() => undefined}
        onAttachCanvasChange={() => undefined}
        onSubmit={() => undefined}
        onInterrupt={() => undefined}
      />,
    );

    expect(html).toContain('aria-label="中断当前处理"');
    expect(html).toContain("Agent 正在读取会话并判断下一步…");
  });
});
