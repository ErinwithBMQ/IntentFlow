export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
};

export type ProjectResponse = {
  id: string;
  name: string;
  root_path: string;
  relative_path: string;
  test_command: string[] | null;
  build_command: string[] | null;
  ignored_names: string[];
  created_at: string;
  updated_at: string;
  last_opened_at: string;
  ready: boolean;
};

export type ProjectTemplate = "empty" | "web";

export type DirectorySelectionResponse = {
  path: string | null;
};

export type CanvasNoteLabel = "idea" | "behavior" | "constraint" | "acceptance";

export type CanvasNote = {
  id: string;
  text: string;
  label: CanvasNoteLabel | null;
  position: { x: number; y: number };
};

export type CanvasConnection = {
  id: string;
  source: string;
  target: string;
  label: string;
};

export type IntentCanvas = {
  notes: CanvasNote[];
  connections: CanvasConnection[];
  supplemental_text: string;
};

export type IntentRequirement = {
  id: string;
  description: string;
  acceptance_criteria: string[];
  source_ids: string[];
};

export type IntentBrief = {
  title: string;
  goal: string;
  requirements: IntentRequirement[];
  constraints: string[];
};

export type TaskDraftSnapshot = {
  id: string;
  session_id: string;
  version: number;
  status: "proposed" | "confirmed";
  source_message_id: string;
  parent_id: string | null;
  canvas: IntentCanvas | null;
  intent: IntentBrief;
  created_at: string;
};

export type IntentCompileResponse = {
  brief: IntentBrief;
  compiler: "ai" | "local";
  notice: string;
};

export type RunStatus = "running" | "completed" | "failed" | "stopped";
export type ReviewStatus = "pending" | "accepted" | "discarded";
export type ApprovalDecision = "allow_once" | "allow_for_run" | "reject";
export type ApprovalStatus = "approval_required" | "approved" | "rejected" | "cancelled";
export type ApprovalMode = "ask" | "auto";
export type VerificationStatus =
  | "not_configured"
  | "command_start_failed"
  | "failed"
  | "passed"
  | "stale";

export type ToolApproval = {
  id: string;
  tool_call_id: string;
  tool_name: string;
  target: string | null;
  reason: string;
  patch: string;
  status: ApprovalStatus;
  decision: ApprovalDecision | null;
};

export type RunEvent = {
  sequence: number;
  kind: "run_started" | "model_turn" | "approval_required" | "approval_resolved" | "tool_started" | "tool_finished" | "run_finished";
  phase: "planning" | "acting" | "verifying" | "finished";
  status: "running" | "succeeded" | "failed" | "stopped";
  action: string;
  reason: string;
  related_requirement_ids: string[];
  tool_name: string | null;
  target: string | null;
  evidence: string[];
  verification_status?: VerificationStatus | null;
  approval_id?: string | null;
  patch?: string | null;
  approval_status?: ApprovalStatus | null;
};

export type RunReport = {
  status: "completed" | "partial" | "failed";
  summary: string;
  evidence: string[];
  unresolved: string[];
  requirement_results: RequirementResult[];
};

export type RequirementResult = {
  requirement_id: string;
  status: "verified" | "implemented" | "failed" | "unresolved";
  summary: string;
  related_files: string[];
  evidence: string[];
};

export type ContextCheckpoint = {
  summary: string;
  covered_history_items: number;
  current_goal: string;
  constraints: string[];
  plan: string[];
  modified_files: string[];
  verification_results: string[];
  approval_decisions: string[];
  unresolved: string[];
  compression_count: number;
  discarded_content_types: string[];
};

export type ContextRoundMetrics = {
  step: number;
  estimated_input_tokens: number;
  actual_input_tokens: number | null;
  output_tokens: number | null;
  compressed: boolean;
  discarded_content_types: string[];
  model_duration_ms: number;
};

export type RunMetrics = {
  model_turns: number;
  tool_calls: number;
  estimated_input_tokens: number;
  actual_input_tokens: number;
  output_tokens: number;
  compression_count: number;
  discarded_content_types: string[];
  duration_ms: number;
  rounds: ContextRoundMetrics[];
};

export type AgentHistoryItem =
  | { action: string; reason: string; related_requirement_ids: string[] }
  | { call_id: string; tool_name: string; ok: boolean; summary: string; output: string }
  | { content: string };

export type RunSnapshot = {
  id: string;
  status: RunStatus;
  review_status: ReviewStatus;
  workspace_relative_path: string;
  workspace_mode?: "isolated" | "direct";
  project_id: string | null;
  project_name: string | null;
  project_ignored_names: string[];
  session_id: string | null;
  trigger_message_id: string | null;
  task_draft_id?: string | null;
  intent: IntentBrief | null;
  approval_mode: "ask" | "auto";
  approvals: ToolApproval[];
  events: RunEvent[];
  report: RunReport | null;
  context_checkpoint: ContextCheckpoint | null;
  metrics: RunMetrics;
  history: AgentHistoryItem[];
};

export type ConversationMode = "ask" | "plan" | "agent";

export type SessionRecord = {
  id: string;
  project_id: string;
  title: string;
  approval_mode: ApprovalMode;
  created_at: string;
  updated_at: string;
};

export type CanvasSnapshotRecord = {
  id: string;
  session_id: string;
  canvas: IntentCanvas;
  created_at: string;
};

export type ConversationMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  mode: ConversationMode;
  content: string;
  canvas_snapshot_id: string | null;
  task_draft_id?: string | null;
  run_id: string | null;
  intent: IntentBrief | null;
  created_at: string;
  sequence: number;
};

export type SessionDetail = {
  session: SessionRecord;
  messages: ConversationMessage[];
  canvas_snapshots: CanvasSnapshotRecord[];
  task_drafts?: TaskDraftSnapshot[];
  runs: RunSnapshot[];
};

export type SendSessionMessageResponse = {
  user_message: ConversationMessage;
  assistant_message: ConversationMessage;
  run: RunSnapshot | null;
  task_draft?: TaskDraftSnapshot | null;
};

export type CancelSessionActivityResponse = {
  cancelled: boolean;
  kind: "message" | "run" | "none";
};

export type WorkspaceScope = "project" | "run";

export type WorkspaceEntry = {
  name: string;
  path: string;
  kind: "directory" | "file";
  children: WorkspaceEntry[];
};

export type WorkspaceTree = {
  root_name: string;
  entries: WorkspaceEntry[];
  truncated: boolean;
};

export type WorkspaceFile = {
  path: string;
  content: string;
  size: number;
  language: string;
};

export type UpdateProjectFileResponse = {
  file: WorkspaceFile;
  run: RunSnapshot | null;
  changes: ChangeSummary | null;
};

export type ChangeKind = "added" | "modified" | "deleted";

export type FileChange = {
  path: string;
  status: ChangeKind;
  additions: number;
  deletions: number;
  viewable: boolean;
  unavailable_reason: "binary" | "invalid_utf8" | "too_large" | null;
};

export type ChangeSummary = {
  files: FileChange[];
  changed_files: number;
  additions: number;
  deletions: number;
};

export type FileDiff = FileChange & {
  diff: string;
};

export type RunPreviewResponse = {
  available: boolean;
  url: string | null;
};

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `请求失败：${response.status}`);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export function getProject(): Promise<ProjectResponse | null> {
  return requestJson<ProjectResponse | null>("/api/project");
}

export function listProjects(): Promise<ProjectResponse[]> {
  return requestJson<ProjectResponse[]>("/api/projects");
}

export function registerProject(path: string): Promise<ProjectResponse> {
  return postJson<ProjectResponse>("/api/projects", { path });
}

export function pickProjectDirectory(): Promise<ProjectResponse | null> {
  return postJson<ProjectResponse | null>("/api/projects/pick-directory");
}

export function pickParentDirectory(): Promise<DirectorySelectionResponse> {
  return postJson<DirectorySelectionResponse>("/api/projects/pick-parent");
}

export function createProject(
  parentPath: string,
  name: string,
  template: ProjectTemplate,
): Promise<ProjectResponse> {
  return postJson<ProjectResponse>("/api/projects/create", {
    parent_path: parentPath,
    name,
    template,
  });
}

export function activateProject(projectId: string): Promise<ProjectResponse> {
  return postJson<ProjectResponse>(`/api/projects/${projectId}/activate`);
}

export function updateProject(
  projectId: string,
  project: Pick<
    ProjectResponse,
    "name" | "test_command" | "build_command" | "ignored_names"
  >,
): Promise<ProjectResponse> {
  return patchJson<ProjectResponse>(`/api/projects/${projectId}`, project);
}

export function listSessions(projectId: string): Promise<SessionRecord[]> {
  return requestJson<SessionRecord[]>(withQuery("/api/sessions", { project_id: projectId }));
}

export function createSession(projectId: string, title = "新对话"): Promise<SessionRecord> {
  return postJson<SessionRecord>("/api/sessions", { title, project_id: projectId });
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return requestJson<SessionDetail>(`/api/sessions/${sessionId}`);
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `删除对话失败：${response.status}`);
  }
}

export function sendSessionMessage(
  sessionId: string,
  content: string,
  approvalMode: ApprovalMode,
  canvas: IntentCanvas | null,
  taskDraftId: string | null = null,
): Promise<SendSessionMessageResponse> {
  return postJson<SendSessionMessageResponse>(`/api/sessions/${sessionId}/messages`, {
    content,
    approval_mode: approvalMode,
    attach_canvas: canvas !== null,
    canvas,
    ...(taskDraftId ? { task_draft_id: taskDraftId } : {}),
  });
}

export function cancelSessionActivity(
  sessionId: string,
): Promise<CancelSessionActivityResponse> {
  return postJson<CancelSessionActivityResponse>(`/api/sessions/${sessionId}/cancel`);
}

export function getProjectTree(projectId: string): Promise<WorkspaceTree> {
  return requestJson<WorkspaceTree>(withQuery("/api/project/tree", { project_id: projectId }));
}

export function getProjectFile(projectId: string, path: string): Promise<WorkspaceFile> {
  return requestJson<WorkspaceFile>(withQuery("/api/project/file", {
    project_id: projectId,
    path,
  }));
}

export function updateProjectFile(
  projectId: string,
  path: string,
  content: string,
  expectedContent: string,
  runId: string | null,
): Promise<UpdateProjectFileResponse> {
  return requestJson<UpdateProjectFileResponse>(withQuery("/api/project/file", {
    project_id: projectId,
    path,
  }), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, expected_content: expectedContent, run_id: runId }),
  });
}

export async function compileIntent(
  canvas: IntentCanvas,
  compiler: "ai" | "local" = "ai",
): Promise<IntentCompileResponse> {
  const response = await fetch("/api/intent/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ canvas, compiler }),
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `意图整理失败：${response.status}`);
  }

  return (await response.json()) as IntentCompileResponse;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `请求失败：${response.status}`);
  }
  return (await response.json()) as T;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `请求失败：${response.status}`);
  }
  return (await response.json()) as T;
}

export function createRun(intent: IntentBrief): Promise<RunSnapshot> {
  return postJson<RunSnapshot>("/api/runs", { intent });
}

export function getRun(runId: string): Promise<RunSnapshot> {
  return requestJson<RunSnapshot>(`/api/runs/${runId}`);
}

export function getRunTree(runId: string): Promise<WorkspaceTree> {
  return requestJson<WorkspaceTree>(`/api/runs/${runId}/tree`);
}

export function getRunFile(runId: string, path: string): Promise<WorkspaceFile> {
  return requestJson<WorkspaceFile>(withPath(`/api/runs/${runId}/file`, path));
}

export function getRunChanges(runId: string): Promise<ChangeSummary> {
  return requestJson<ChangeSummary>(`/api/runs/${runId}/changes`);
}

export function getRunFileDiff(runId: string, path: string): Promise<FileDiff> {
  return requestJson<FileDiff>(withPath(`/api/runs/${runId}/diff`, path));
}

export function getRunPreview(runId: string): Promise<RunPreviewResponse> {
  return requestJson<RunPreviewResponse>(`/api/runs/${runId}/preview`);
}

export function stopRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/stop`);
}

export function resolveRunApproval(
  runId: string,
  approvalId: string,
  decision: ApprovalDecision,
): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/approvals/${approvalId}`, { decision });
}

export function acceptRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/accept`);
}

export function discardRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/discard`);
}

export function keepRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/keep`);
}

export function undoRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/undo`);
}

export function subscribeToRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onClosed: () => void,
  onError: () => void,
): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.addEventListener("run_event", (message) => {
    const event = JSON.parse((message as MessageEvent<string>).data) as RunEvent;
    onEvent(event);
    if (event.kind === "run_finished") {
      source.close();
      onClosed();
    }
  });
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}

function withPath(endpoint: string, path: string): string {
  return `${endpoint}?${new URLSearchParams({ path }).toString()}`;
}

function withQuery(endpoint: string, parameters: Record<string, string>): string {
  return `${endpoint}?${new URLSearchParams(parameters).toString()}`;
}
