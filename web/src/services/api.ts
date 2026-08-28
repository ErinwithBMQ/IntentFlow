export type HealthResponse = {
  status: "ok";
  service: string;
  version: string;
};

export type ProjectResponse = {
  name: string;
  relativePath: string;
  ready: boolean;
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

export type IntentCompileResponse = {
  brief: IntentBrief;
  compiler: "ai" | "local";
  notice: string;
};

export type RunStatus = "running" | "completed" | "failed" | "stopped";

export type RunEvent = {
  sequence: number;
  kind: "run_started" | "model_turn" | "tool_started" | "tool_finished" | "run_finished";
  phase: "planning" | "acting" | "verifying" | "finished";
  status: "running" | "succeeded" | "failed" | "stopped";
  action: string;
  reason: string;
  related_requirement_ids: string[];
  tool_name: string | null;
  target: string | null;
  evidence: string[];
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

export type RunSnapshot = {
  id: string;
  status: RunStatus;
  workspace_relative_path: string;
  events: RunEvent[];
  report: RunReport | null;
};

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(path);

  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export function getProject(): Promise<ProjectResponse> {
  return requestJson<ProjectResponse>("/api/project");
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

export function createRun(intent: IntentBrief): Promise<RunSnapshot> {
  return postJson<RunSnapshot>("/api/runs", { intent });
}

export function getRun(runId: string): Promise<RunSnapshot> {
  return requestJson<RunSnapshot>(`/api/runs/${runId}`);
}

export function stopRun(runId: string): Promise<RunSnapshot> {
  return postJson<RunSnapshot>(`/api/runs/${runId}/stop`);
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
