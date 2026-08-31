import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { IntentBrief, RunSnapshot } from "../../services/api";
import { SingleRunConversation } from "./SingleRunConversation";

const brief: IntentBrief = {
  title: "Static page",
  goal: "Build a static page",
  requirements: [],
  constraints: [],
};

function runSnapshot(status: RunSnapshot["status"], evidence: string[] = []): RunSnapshot {
  return {
    id: "run-1",
    status,
    review_status: "pending",
    workspace_relative_path: "runtime-data/runs/run-1/workspace",
    project_id: "project-1",
    project_name: "demo",
    project_ignored_names: [],
    session_id: "session-1",
    trigger_message_id: "message-1",
    intent: brief,
    approval_mode: "ask",
    approvals: [],
    events: [],
    report: {
      status: status === "completed" ? "completed" : "partial",
      summary: "Implemented",
      evidence,
      unresolved: [],
      requirement_results: [],
    },
    context_checkpoint: null,
    metrics: {
      model_turns: 0,
      tool_calls: 0,
      estimated_input_tokens: 0,
      actual_input_tokens: 0,
      output_tokens: 0,
      compression_count: 0,
      discarded_content_types: [],
      duration_ms: 0,
      rounds: [],
    },
    history: [],
  };
}

function renderReview(run: RunSnapshot) {
  return renderToStaticMarkup(
    <SingleRunConversation
      brief={brief}
      run={run}
      runError=""
      changes={{ files: [], changed_files: 1, additions: 1, deletions: 0 }}
      reviewAction={null}
      toolApprovalAction={null}
      reviewError=""
      onHighlightSources={() => undefined}
      onOpenRelatedFile={() => undefined}
      onKeep={() => undefined}
      onUndo={() => undefined}
      onResolveApproval={() => undefined}
    />,
  );
}

describe("SingleRunConversation review actions", () => {
  it("allows an unverified completed run to be kept with a warning", () => {
    const html = renderReview(runSnapshot("completed"));

    expect(html).toContain("没有自动化验证结果");
    expect(html).toContain("仍然保留修改");
  });

  it("allows a failed run to be deliberately kept", () => {
    const html = renderReview(runSnapshot("failed"));

    expect(html).toContain("当前项目可能包含不完整修改");
    expect(html).toContain("仍然保留修改");
  });

  it("keeps the normal action for a verified completed run", () => {
    const html = renderReview(runSnapshot("completed", ["Build passed"]));

    expect(html).toContain("保留修改");
    expect(html).not.toContain("仍然保留修改");
  });
});
