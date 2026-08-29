import { afterEach, describe, expect, it, vi } from "vitest";

import {
  compileIntent,
  createRun,
  getHealth,
  getProjectFile,
  getProjectTree,
  getRunChanges,
  getRunFile,
  getRunFileDiff,
  getRunTree,
  stopRun,
  type IntentCanvas,
} from "./api";

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

  it("requests project and run workspace facts with encoded paths", async () => {
    const tree = { root_name: "todo-demo", entries: [], truncated: false };
    const file = {
      path: "src/tasks file.js",
      content: "export const tasks = [];",
      size: 24,
      language: "javascript",
    };
    const changes = { files: [], changed_files: 0, additions: 0, deletions: 0 };
    const diff = {
      path: "src/tasks file.js",
      status: "modified",
      additions: 1,
      deletions: 1,
      viewable: true,
      unavailable_reason: null,
      diff: "--- a/src/tasks file.js\n+++ b/src/tasks file.js\n",
    };
    const payloads = [tree, file, tree, file, changes, diff];
    const fetchMock = vi.fn().mockImplementation(() => {
      const payload = payloads.shift();
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await getProjectTree();
    await getProjectFile("src/tasks file.js");
    await getRunTree("run-1");
    await getRunFile("run-1", "src/tasks file.js");
    await getRunChanges("run-1");
    await getRunFileDiff("run-1", "src/tasks file.js");

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/project/tree",
      "/api/project/file?path=src%2Ftasks+file.js",
      "/api/runs/run-1/tree",
      "/api/runs/run-1/file?path=src%2Ftasks+file.js",
      "/api/runs/run-1/changes",
      "/api/runs/run-1/diff?path=src%2Ftasks+file.js",
    ]);
  });

  it("surfaces a backend file error without exposing a generic status only", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "二进制文件不能作为文本查看" }), {
          status: 415,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(getProjectFile("image.bin")).rejects.toThrow("二进制文件不能作为文本查看");
  });
});
