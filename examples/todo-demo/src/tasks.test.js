import { describe, expect, it } from "vitest";

import { countOpenTasks, initialTasks } from "./tasks";

describe("countOpenTasks", () => {
  it("counts unfinished tasks", () => {
    expect(countOpenTasks(initialTasks)).toBe(2);
  });
});

