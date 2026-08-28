import { afterEach, describe, expect, it, vi } from "vitest";

import { compileIntent, createRun, getHealth, stopRun, type IntentCanvas } from "./api";

describe("getHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the backend health payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ status: "ok", service: "intentflow-server", version: "0.1.0" }),
          { status: 200 },
        ),
      ),
    );

    await expect(getHealth()).resolves.toEqual({
      status: "ok",
      service: "intentflow-server",
      version: "0.1.0",
    });
  });

  it("reports a failed backend request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(getHealth()).rejects.toThrow("请求失败：503");
  });

  it("sends the free canvas to the intent compiler", async () => {
    const canvas: IntentCanvas = {
      notes: [
        {
          id: "note-1",
          text: "提交后显示任务",
          label: null,
          position: { x: 10, y: 20 },
        },
      ],
      connections: [],
      supplemental_text: "保持简单",
    };
    const result = {
      brief: {
        title: "添加任务",
        goal: "提交后显示任务",
        requirements: [],
        constraints: ["保持简单"],
      },
      compiler: "local",
      notice: "使用本地基线整理。",
    };
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(result), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(compileIntent(canvas)).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/intent/compile",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ canvas, compiler: "ai" }),
      }),
    );

    await compileIntent(canvas, "local");
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/intent/compile",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ canvas, compiler: "local" }),
      }),
    );
  });

  it("starts and stops an Agent run", async () => {
    const brief = {
      title: "添加任务",
      goal: "提交后显示任务",
      requirements: [],
      constraints: [],
    };
    const snapshot = {
      id: "run-1",
      status: "running",
      workspace_relative_path: "runtime-data/runs/run-1/todo-demo",
      events: [],
      report: null,
    };
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(snapshot), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(createRun(brief)).resolves.toEqual(snapshot);
    await stopRun("run-1");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/runs",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ intent: brief }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/runs/run-1/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
