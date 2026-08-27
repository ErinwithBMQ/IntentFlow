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

