import { describe, expect, it } from "vitest";

import { TODO_EXAMPLE_EDGES, TODO_EXAMPLE_NODES, toIntentCanvas } from "./canvasState";

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
