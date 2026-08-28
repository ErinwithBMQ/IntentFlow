import { describe, expect, it } from "vitest";

import type { RunEvent } from "../../services/api";
import { buildConversationActivities } from "./conversation";

function event(values: Partial<RunEvent> & Pick<RunEvent, "sequence" | "kind">): RunEvent {
  return {
    phase: "acting",
    status: "running",
    action: "",
    reason: "",
    related_requirement_ids: [],
    tool_name: null,
    target: null,
    evidence: [],
    ...values,
  };
}

describe("buildConversationActivities", () => {
  it("pairs tool events and groups consecutive file inspection", () => {
    const activities = buildConversationActivities([
      event({ sequence: 1, kind: "run_started", phase: "planning", action: "开始" }),
      event({ sequence: 2, kind: "model_turn", phase: "planning", action: "先读取文件" }),
      event({ sequence: 3, kind: "tool_started", tool_name: "list_files", action: "查看目录" }),
      event({
        sequence: 4,
        kind: "tool_finished",
        tool_name: "list_files",
        status: "succeeded",
        action: "已查看目录",
      }),
      event({ sequence: 5, kind: "model_turn", phase: "planning", action: "读取入口" }),
      event({
        sequence: 6,
        kind: "tool_started",
        tool_name: "read_file",
        target: "src/App.tsx",
        action: "读取入口",
      }),
      event({
        sequence: 7,
        kind: "tool_finished",
        tool_name: "read_file",
        target: "src/App.tsx",
        status: "succeeded",
        action: "已读取入口",
      }),
    ]);

    expect(activities).toHaveLength(1);
    expect(activities[0]).toMatchObject({
      stage: "locating",
      status: "succeeded",
      title: "已定位相关代码",
    });
    expect(activities[0].actions).toHaveLength(2);
    expect(activities[0].actions[1]).toMatchObject({
      action: "已读取入口",
      target: "src/App.tsx",
      status: "succeeded",
    });
  });

  it("keeps failed verification visible and preserves its evidence", () => {
    const activities = buildConversationActivities([
      event({
        sequence: 1,
        kind: "tool_started",
        phase: "verifying",
        tool_name: "run_command",
        target: "test",
        action: "运行测试",
        related_requirement_ids: ["REQ-01"],
      }),
      event({
        sequence: 2,
        kind: "tool_finished",
        phase: "verifying",
        tool_name: "run_command",
        target: "test",
        status: "failed",
        action: "测试退出码为 1",
        related_requirement_ids: ["REQ-01"],
        evidence: ["1 test failed"],
      }),
      event({
        sequence: 3,
        kind: "run_finished",
        phase: "finished",
        status: "failed",
        action: "任务失败",
      }),
    ]);

    expect(activities).toHaveLength(1);
    expect(activities[0]).toMatchObject({
      stage: "verifying",
      status: "failed",
      title: "验证未通过",
      requirementIds: ["REQ-01"],
    });
    expect(activities[0].actions[0].evidence).toEqual(["1 test failed"]);
  });

  it("shows an unmatched latest model turn as current planning", () => {
    const activities = buildConversationActivities([
      event({
        sequence: 1,
        kind: "model_turn",
        phase: "planning",
        action: "准备修复失败测试",
        reason: "测试结果显示空输入仍被提交",
      }),
    ]);

    expect(activities).toEqual([
      expect.objectContaining({
        stage: "planning",
        status: "running",
        title: "准备修复失败测试",
        reason: "测试结果显示空输入仍被提交",
        actions: [],
      }),
    ]);
  });

  it("starts a new activity when the execution stage changes", () => {
    const activities = buildConversationActivities([
      event({ sequence: 1, kind: "tool_started", tool_name: "read_file" }),
      event({
        sequence: 2,
        kind: "tool_finished",
        tool_name: "read_file",
        status: "succeeded",
      }),
      event({ sequence: 3, kind: "tool_started", tool_name: "apply_patch" }),
      event({
        sequence: 4,
        kind: "tool_finished",
        tool_name: "apply_patch",
        status: "succeeded",
      }),
      event({
        sequence: 5,
        kind: "tool_started",
        phase: "verifying",
        tool_name: "run_command",
      }),
    ]);

    expect(activities.map((activity) => activity.stage)).toEqual([
      "locating",
      "implementing",
      "verifying",
    ]);
    expect(activities[2].status).toBe("running");
  });
});
