import { describe, expect, it } from "vitest";

import {
  DEFAULT_CANVAS_EDGES,
  DEFAULT_CANVAS_NODES,
  edgeChangesInvalidateIntent,
  fromIntentCanvas,
  nodeChangesInvalidateIntent,
  toIntentCanvas,
} from "./canvasState";

describe("toIntentCanvas", () => {
  it("preserves note IDs, free labels, positions, and connection text", () => {
    const canvas = toIntentCanvas(
      DEFAULT_CANVAS_NODES,
      DEFAULT_CANVAS_EDGES,
    );

    expect(canvas.notes[0]).toMatchObject({
      id: "idea-goal",
      label: "idea",
      position: { x: 100, y: 110 },
    });
    expect(canvas.connections[0]).toMatchObject({ label: "拆分为" });
    expect(canvas.supplemental_text).toBe("");
  });

  it("restores a persisted canvas into editable React Flow state", () => {
    const canvas = toIntentCanvas(DEFAULT_CANVAS_NODES, DEFAULT_CANVAS_EDGES);
    canvas.supplemental_text = "旧快照中的补充说明";

    const restored = fromIntentCanvas(canvas);

    expect(restored.nodes).toEqual(DEFAULT_CANVAS_NODES);
    expect(restored.edges).toEqual(DEFAULT_CANVAS_EDGES);
    expect(restored).not.toHaveProperty("supplementalText");
  });
});

describe("intent invalidation", () => {
  it("keeps a compiled brief when nodes only move or resize", () => {
    expect(nodeChangesInvalidateIntent([
      { type: "position", id: "idea-goal", position: { x: 12, y: 18 }, dragging: true },
      { type: "dimensions", id: "idea-goal", dimensions: { width: 220, height: 120 } },
      { type: "select", id: "idea-goal", selected: true },
    ])).toBe(false);
  });

  it("invalidates a compiled brief when notes or connections change", () => {
    expect(nodeChangesInvalidateIntent([{ type: "remove", id: "idea-goal" }])).toBe(true);
    expect(edgeChangesInvalidateIntent([{ type: "remove", id: "edge-goal-behavior" }])).toBe(true);
    expect(edgeChangesInvalidateIntent([{ type: "select", id: "edge-goal-behavior", selected: true }])).toBe(false);
  });
});
