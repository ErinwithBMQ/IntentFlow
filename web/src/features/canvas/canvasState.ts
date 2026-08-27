import type { Edge, Node } from "@xyflow/react";

import type { CanvasNoteLabel, IntentCanvas } from "../../services/api";

export type NoteData = {
  text: string;
  label: CanvasNoteLabel | null;
};

export type NoteNode = Node<NoteData, "note">;

export const TODO_EXAMPLE_NODES: NoteNode[] = [
  {
    id: "idea-add-task",
    type: "note",
    position: { x: 100, y: 110 },
    data: { text: "我想让用户能快速添加一个待办", label: "idea" },
  },
  {
    id: "behavior-submit",
    type: "note",
    position: { x: 400, y: 80 },
    data: { text: "输入内容，点击按钮后立刻出现在列表里", label: "behavior" },
  },
  {
    id: "acceptance-empty",
    type: "note",
    position: { x: 420, y: 280 },
    data: { text: "如果什么都没写，就不要添加", label: "acceptance" },
  },
  {
    id: "constraint-style",
    type: "note",
    position: { x: 110, y: 340 },
    data: { text: "尽量保持现在简洁的页面样式", label: "constraint" },
  },
];

export const TODO_EXAMPLE_EDGES: Edge[] = [
  {
    id: "edge-idea-behavior",
    source: "idea-add-task",
    target: "behavior-submit",
    label: "具体来说",
  },
  {
    id: "edge-behavior-empty",
    source: "behavior-submit",
    target: "acceptance-empty",
    label: "同时保证",
  },
];

export function toIntentCanvas(
  nodes: NoteNode[],
  edges: Edge[],
  supplementalText: string,
): IntentCanvas {
  return {
    notes: nodes.map((node) => ({
      id: node.id,
      text: node.data.text,
      label: node.data.label,
      position: node.position,
    })),
    connections: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: typeof edge.label === "string" ? edge.label : "",
    })),
    supplemental_text: supplementalText,
  };
}

export function isStoredCanvas(value: unknown): value is {
  nodes: NoteNode[];
  edges: Edge[];
  supplementalText: string;
} {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    Array.isArray(candidate.nodes) &&
    Array.isArray(candidate.edges) &&
    typeof candidate.supplementalText === "string"
  );
}
