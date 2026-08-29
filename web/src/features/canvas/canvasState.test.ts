import { describe, expect, it } from "vitest";

import {
  TODO_EXAMPLE_EDGES,
  TODO_EXAMPLE_NODES,
  edgeChangesInvalidateIntent,
  nodeChangesInvalidateIntent,
  toIntentCanvas,
} from "./canvasState";

describe("toIntentCanvas", () => {
  it("preserves note IDs, free labels, positions, and connection text", () => {
    const canvas = toIntentCanvas(
      TODO_EXAMPLE_NODES,
      TODO_EXAMPLE_EDGES,
      "还有一句补充说明",
    );

    expect(canvas.notes[0]).toMatchObject({
      id: "idea-add-task",
      label: "idea",
      position: { x: 100, y: 110 },
    });
    expect(canvas.connections[0]).toMatchObject({ label: "具体来说" });
    expect(canvas.supplemental_text).toBe("还有一句补充说明");
  });
});

describe("intent invalidation", () => {
  it("keeps a compiled brief when nodes only move or resize", () => {
    expect(nodeChangesInvalidateIntent([
      { type: "position", id: "idea-add-task", position: { x: 12, y: 18 }, dragging: true },
      { type: "dimensions", id: "idea-add-task", dimensions: { width: 220, height: 120 } },
      { type: "select", id: "idea-add-task", selected: true },
    ])).toBe(false);
  });

  it("invalidates a compiled brief when notes or connections change", () => {
    expect(nodeChangesInvalidateIntent([{ type: "remove", id: "idea-add-task" }])).toBe(true);
    expect(edgeChangesInvalidateIntent([{ type: "remove", id: "edge-idea-behavior" }])).toBe(true);
    expect(edgeChangesInvalidateIntent([{ type: "select", id: "edge-idea-behavior", selected: true }])).toBe(false);
  });
});
