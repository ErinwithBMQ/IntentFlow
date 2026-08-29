import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../services/api";
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

  it("shows a mode-specific response indicator", () => {
    const html = renderToStaticMarkup(
      <SessionConversation
        messages={[assistantMessage("上一条回复")]}
        runs={[]}
        selectedRunId={null}
        selectedRunDetail={null}
        respondingMode="plan"
        onSelectRun={() => undefined}
      />,
    );

    expect(html).toContain("正在阅读项目并整理计划…");
  });
});
