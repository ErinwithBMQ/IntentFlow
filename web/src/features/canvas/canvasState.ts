import type { Edge, EdgeChange, Node, NodeChange } from "@xyflow/react";

import type { CanvasNoteLabel, IntentCanvas } from "../../services/api";

export type NoteData = {
  text: string;
  label: CanvasNoteLabel | null;
};

export type NoteNode = Node<NoteData, "note">;

export type StoredCanvas = {
  nodes: NoteNode[];
  edges: Edge[];
};

export const DEFAULT_CANVAS_NODES: NoteNode[] = [
  {
    id: "idea-goal",
    type: "note",
    position: { x: 100, y: 110 },
    data: { text: "描述你希望 Agent 完成的目标", label: "idea" },
  },
  {
    id: "behavior-change",
    type: "note",
    position: { x: 400, y: 80 },
    data: { text: "列出需要实现或调整的具体行为", label: "behavior" },
  },
  {
    id: "acceptance-check",
    type: "note",
    position: { x: 420, y: 280 },
    data: { text: "写下可以检查的完成标准", label: "acceptance" },
  },
  {
    id: "constraint-boundary",
    type: "note",
    position: { x: 110, y: 340 },
    data: { text: "补充不能改变的内容或技术限制", label: "constraint" },
  },
];

export const DEFAULT_CANVAS_EDGES: Edge[] = [
  {
    id: "edge-goal-behavior",
    source: "idea-goal",
    target: "behavior-change",
    label: "拆分为",
  },
  {
    id: "edge-behavior-acceptance",
    source: "behavior-change",
    target: "acceptance-check",
    label: "验收方式",
  },
];

export function toIntentCanvas(
  nodes: NoteNode[],
  edges: Edge[],
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
    supplemental_text: "",
  };
}

export function fromIntentCanvas(canvas: IntentCanvas): StoredCanvas {
  return {
    nodes: canvas.notes.map((note) => ({
      id: note.id,
      type: "note",
      position: note.position,
      data: { text: note.text, label: note.label },
    })),
    edges: canvas.connections.map((connection) => ({
      id: connection.id,
      source: connection.source,
      target: connection.target,
      label: connection.label,
    })),
  };
}

export function isStoredCanvas(value: unknown): value is StoredCanvas {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    Array.isArray(candidate.nodes) &&
    Array.isArray(candidate.edges)
  );
}

export function nodeChangesInvalidateIntent(changes: NodeChange<NoteNode>[]): boolean {
  return changes.some((change) => (
    change.type === "add" || change.type === "remove" || change.type === "replace"
  ));
}

export function edgeChangesInvalidateIntent(changes: EdgeChange[]): boolean {
  return changes.some((change) => (
    change.type === "add" || change.type === "remove" || change.type === "replace"
  ));
}
