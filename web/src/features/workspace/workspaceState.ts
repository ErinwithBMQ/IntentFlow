import type { ChangeSummary, WorkspaceScope } from "../../services/api";

export type WorkspaceTab = "canvas" | "code" | "diff";

export function workspaceFileKey(scope: WorkspaceScope, path: string): string {
  return `${scope}:${path}`;
}

export function relatedFileDestination(
  changes: ChangeSummary | null,
  path: string,
): "code" | "diff" {
  return changes?.files.some((change) => change.path === path) ? "diff" : "code";
}

export function diffLineKind(
  line: string,
): "addition" | "deletion" | "header" | "hunk" | "context" {
  if (line.startsWith("+++") || line.startsWith("---")) return "header";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "addition";
  if (line.startsWith("-")) return "deletion";
  return "context";
}
