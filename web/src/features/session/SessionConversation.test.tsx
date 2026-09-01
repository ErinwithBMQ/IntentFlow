import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  ConversationMessage,
  IntentBrief,
  TaskDraftSnapshot,
} from "../../services/api";
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
    task_draft_id: null,
    run_id: null,
    intent: null,
    created_at: "2026-08-29T00:00:00Z",
    sequence: 1,
  };
}

const intent: IntentBrief = {
  title: "优化 2048 页面",
  goal: "让页面视觉更简洁",
  requirements: [
    {
      id: "REQ-01",
      description: "删除副标题文本",
      acceptance_criteria: [],
      source_ids: [],
    },
  ],
  constraints: [],
};

const taskDraft: TaskDraftSnapshot = {
  id: "task-draft-1",
  session_id: "session-1",
  version: 2,
  status: "proposed",
  source_message_id: "message-user-1",
  parent_id: null,
  canvas: {
    notes: [
      {
        id: "draft-goal",
        text: intent.goal,
        label: "idea",
        position: { x: 80, y: 120 },
      },
    ],
    connections: [],
    supplemental_text: "",
  },
  intent,
  created_at: "2026-08-31T00:00:00Z",
};

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
        taskDrafts={[]}
        selectedRunId={null}
        selectedRunDetail={null}
        responding
        onSelectRun={() => undefined}
        onPreviewTaskDraft={() => undefined}
      />,
    );

    expect(html).toContain("正在读取会话并判断下一步…");
    expect(html).not.toContain("Ask");
  });

  it("collapses the task breakdown by default", () => {
    const message = assistantMessage("收到，我会处理《优化 2048 页面》。");
    message.intent = intent;
    message.task_draft_id = taskDraft.id;

    const html = renderToStaticMarkup(
      <SessionConversation
        messages={[message]}
        runs={[]}
        taskDrafts={[taskDraft]}
        selectedRunId={null}
        selectedRunDetail={null}
        responding={false}
        onSelectRun={() => undefined}
        onPreviewTaskDraft={() => undefined}
      />,
    );

    expect(html).toContain('<details class="session-intent-brief">');
    expect(html).not.toContain('<details class="session-intent-brief" open="">');
    expect(html).toContain("查看任务草案 v2 · 1 项");
    expect(html).toContain("在 Canvas 中预览");
    expect(html).toContain("删除副标题文本");
    expect(html).not.toContain("REQ-01");
  });

  it("uses one Agent input with an independent approval selector", () => {
    const html = renderToStaticMarkup(
      <ConversationComposer
        value="解释上一轮结果"
        approvalMode="ask"
        models={["deepseek-chat", "deepseek-reasoner"]}
        activeModel="deepseek-chat"
        modelSwitching={false}
        attachCanvas={false}
        canvasPlanMode={false}
        sending={false}
        activityRunning={false}
        interrupting={false}
        pendingReviewNotice="上一轮修改待审查，你仍可继续提问"
        error=""
        onChange={() => undefined}
        onApprovalModeChange={() => undefined}
        onModelChange={() => undefined}
        onAttachCanvasChange={() => undefined}
        onCanvasPlanModeChange={() => undefined}
        onSubmit={() => undefined}
        onInterrupt={() => undefined}
      />,
    );

    expect(html).toContain("Agent 权限");
    expect(html).toContain("请求批准");
    expect(html).toContain("当前模型");
    expect(html).toContain("deepseek-reasoner");
    expect(html).toContain("规划 Canvas 模式");
    expect(html).toContain("开启后，Agent 在执行任务前会先为你进行规划");
    expect(html).not.toContain("上一轮修改待审查，你仍可继续提问");
    expect(html).not.toContain(">Plan<");
  });

  it("replaces send with interrupt while the Agent is active", () => {
    const html = renderToStaticMarkup(
      <ConversationComposer
        value=""
        approvalMode="ask"
        models={["deepseek-chat"]}
        activeModel="deepseek-chat"
        modelSwitching={false}
        attachCanvas={false}
        canvasPlanMode
        sending
        activityRunning={false}
        interrupting={false}
        pendingReviewNotice=""
        error=""
        onChange={() => undefined}
        onApprovalModeChange={() => undefined}
        onModelChange={() => undefined}
        onAttachCanvasChange={() => undefined}
        onCanvasPlanModeChange={() => undefined}
        onSubmit={() => undefined}
        onInterrupt={() => undefined}
      />,
    );

    expect(html).toContain('aria-label="中断当前处理"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("Agent 正在读取会话并判断下一步…");
  });
});
