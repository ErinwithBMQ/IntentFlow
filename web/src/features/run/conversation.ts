import type { RunEvent } from "../../services/api";

export type ConversationStage =
  | "planning"
  | "locating"
  | "implementing"
  | "verifying"
  | "reporting";

export type ConversationAction = {
  id: string;
  toolName: string | null;
  target: string | null;
  status: RunEvent["status"];
  action: string;
  reason: string;
  requirementIds: string[];
  evidence: string[];
  verificationStatus: RunEvent["verification_status"];
};

export const verificationStatusText = {
  not_configured: "未配置验证",
  command_start_failed: "命令无法启动",
  failed: "验证失败",
  passed: "验证通过",
} as const;

export type ConversationActivity = {
  id: string;
  stage: ConversationStage;
  status: RunEvent["status"];
  title: string;
  reason: string;
  requirementIds: string[];
  actions: ConversationAction[];
};

export function buildConversationActivities(events: RunEvent[]): ConversationActivity[] {
  const activities: ConversationActivity[] = [];
  let pendingTurn: RunEvent | null = null;

  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    if (event.kind === "model_turn") {
      pendingTurn = event;
      continue;
    }

    if (event.kind === "tool_started") {
      const stage = toolStage(event.tool_name, event.phase);
      const activity = appendActivity(activities, stage, event, pendingTurn);
      activity.actions.push(toAction(event));
      refreshActivity(activity);
      pendingTurn = null;
      continue;
    }

    if (event.kind === "tool_finished") {
      const action = findPendingAction(activities, event.tool_name);
      if (action) {
        action.status = event.status;
        action.action = verificationActionText(event);
        action.reason = event.reason || action.reason;
        action.target = event.target ?? action.target;
        action.requirementIds = unique([
          ...action.requirementIds,
          ...event.related_requirement_ids,
        ]);
        action.evidence = unique([...action.evidence, ...event.evidence]);
        action.verificationStatus = event.verification_status ?? action.verificationStatus;
        const owner = activities.find((activity) => activity.actions.includes(action));
        if (owner) refreshActivity(owner);
      } else {
        const stage = toolStage(event.tool_name, event.phase);
        const activity = appendActivity(activities, stage, event, pendingTurn);
        activity.actions.push(toAction(event));
        refreshActivity(activity);
      }
      pendingTurn = null;
    }
  }

  if (pendingTurn) {
    activities.push({
      id: `activity-${pendingTurn.sequence}`,
      stage: "planning",
      status: pendingTurn.status,
      title: pendingTurn.action,
      reason: pendingTurn.reason,
      requirementIds: pendingTurn.related_requirement_ids,
      actions: [],
    });
  }

  return activities;
}

function appendActivity(
  activities: ConversationActivity[],
  stage: ConversationStage,
  event: RunEvent,
  pendingTurn: RunEvent | null,
): ConversationActivity {
  const latest = activities.at(-1);
  if (latest?.stage === stage && latest.actions.length > 0) return latest;

  const activity: ConversationActivity = {
    id: `activity-${event.sequence}`,
    stage,
    status: event.status,
    title: stageTitle(stage, event.status),
    reason: event.reason || pendingTurn?.reason || "",
    requirementIds: unique([
      ...(pendingTurn?.related_requirement_ids ?? []),
      ...event.related_requirement_ids,
    ]),
    actions: [],
  };
  activities.push(activity);
  return activity;
}

function refreshActivity(activity: ConversationActivity) {
  activity.status = activity.actions.some((action) => action.status === "failed")
    ? "failed"
    : activity.actions.some((action) => action.status === "stopped")
      ? "stopped"
      : activity.actions.some((action) => action.status === "running")
        ? "running"
        : "succeeded";
  activity.title = stageTitle(activity.stage, activity.status);
  activity.requirementIds = unique([
    ...activity.requirementIds,
    ...activity.actions.flatMap((action) => action.requirementIds),
  ]);
}

function findPendingAction(
  activities: ConversationActivity[],
  toolName: string | null,
): ConversationAction | undefined {
  for (const activity of [...activities].reverse()) {
    const action = [...activity.actions]
      .reverse()
      .find((item) => item.status === "running" && item.toolName === toolName);
    if (action) return action;
  }
  return undefined;
}

function toAction(event: RunEvent): ConversationAction {
  return {
    id: `action-${event.sequence}`,
    toolName: event.tool_name,
    target: event.target,
    status: event.status,
    action: verificationActionText(event),
    reason: event.reason,
    requirementIds: event.related_requirement_ids,
    evidence: event.evidence,
    verificationStatus: event.verification_status,
  };
}

function verificationActionText(event: RunEvent): string {
  if (event.tool_name !== "run_command" || !event.verification_status) return event.action;
  const command = event.target ?? "验证";
  return {
    not_configured: `${command} 未配置验证命令`,
    command_start_failed: `${command} 验证命令无法启动`,
    failed: `${command} 验证失败`,
    passed: `${command} 验证通过`,
  }[event.verification_status];
}

function toolStage(
  toolName: string | null,
  fallbackPhase: RunEvent["phase"],
): ConversationStage {
  if (toolName === "list_files" || toolName === "read_file") return "locating";
  if (toolName === "apply_patch") return "implementing";
  if (toolName === "run_command") return "verifying";
  if (toolName === "report_result") return "reporting";
  if (fallbackPhase === "verifying") return "verifying";
  return "implementing";
}

function stageTitle(stage: ConversationStage, status: RunEvent["status"]): string {
  if (stage === "planning") return "正在规划下一步";

  const labels = {
    locating: ["定位相关代码", "已定位相关代码", "定位代码时遇到问题"],
    implementing: ["实现代码修改", "已完成代码修改", "修改代码时遇到问题"],
    verifying: ["运行验证", "验证已通过", "验证未通过"],
    reporting: ["整理本轮结果", "已整理本轮结果", "结果报告未通过校验"],
  } as const;
  const [running, succeeded, failed] = labels[stage];
  if (status === "running") return `正在${running}`;
  if (status === "succeeded") return succeeded;
  return failed;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
