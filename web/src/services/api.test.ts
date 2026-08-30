import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptRun,
  cancelSessionActivity,
  compileIntent,
  createRun,
  createSession,
  deleteSession,
  discardRun,
  getHealth,
  getProjectFile,
  getProjectTree,
  getRunChanges,
  getRunFile,
  getRunFileDiff,
  getRunTree,
  getSession,
  listSessions,
  resolveRunApproval,
  sendSessionMessage,
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
      review_status: "pending",
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

  it("accepts and discards a completed run", async () => {
    const snapshot = {
      id: "run-1",
      status: "completed",
      review_status: "accepted",
      workspace_relative_path: "runtime-data/runs/run-1/todo-demo",
      events: [],
      report: null,
    };
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(snapshot), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await acceptRun("run-1");
    await discardRun("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/runs/run-1/accept",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/runs/run-1/discard",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("resolves a pending tool approval", async () => {
    const snapshot = {
      id: "run-1",
      status: "running",
      review_status: "pending",
      approval_mode: "auto",
      approvals: [],
      workspace_relative_path: "runtime-data/runs/run-1/todo-demo",
      events: [],
      report: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(snapshot), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await resolveRunApproval("run-1", "approval-1", "allow_for_run");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runs/run-1/approvals/approval-1",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ decision: "allow_for_run" }),
      }),
    );
  });

  it("creates, lists, reads, and sends messages to a session", async () => {
    const session = {
      id: "session-1",
      project_id: "todo-demo",
      title: "新对话",
      approval_mode: "ask" as const,
      created_at: "2026-08-29T00:00:00Z",
      updated_at: "2026-08-29T00:00:00Z",
    };
    const detail = { session, messages: [], canvas_snapshots: [], runs: [] };
    const sent = {
      user_message: {
        id: "message-1",
        session_id: session.id,
        role: "user",
        mode: "agent",
        content: "增加筛选功能",
        canvas_snapshot_id: null,
        run_id: "run-1",
        intent: null,
        created_at: session.created_at,
        sequence: 1,
      },
      assistant_message: {
        id: "message-2",
        session_id: session.id,
        role: "assistant",
        mode: "agent",
        content: "开始执行",
        canvas_snapshot_id: null,
        run_id: "run-1",
        intent: null,
        created_at: session.created_at,
        sequence: 2,
      },
      run: null,
    };
    const payloads = [[session], session, detail, sent];
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(payloads.shift()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    await listSessions();
    await createSession();
    await getSession(session.id);
    await sendSessionMessage(session.id, "增加筛选功能", "auto", null);

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/sessions",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ title: "新对话" }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/sessions/session-1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          content: "增加筛选功能",
          approval_mode: "auto",
          attach_canvas: false,
          canvas: null,
        }),
      }),
    );
  });

  it("deletes a session", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteSession("session-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-1",
      { method: "DELETE" },
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

  it("cancels the active session activity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ cancelled: true, kind: "message" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(cancelSessionActivity("session-1")).resolves.toEqual({
      cancelled: true,
      kind: "message",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
