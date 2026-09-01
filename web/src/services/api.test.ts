import { afterEach, describe, expect, it, vi } from "vitest";

import {
  activateProject,
  cancelSessionActivity,
  compileIntent,
  createProject,
  createRun,
  createSession,
  deleteSession,
  getHealth,
  getProjectFile,
  getProjectTree,
  getRunChanges,
  getRunFile,
  getRunFileDiff,
  getRunTree,
  getSession,
  keepRun,
  listProjects,
  listSessions,
  registerProject,
  resolveRunApproval,
  sendSessionMessage,
  stopRun,
  undoRun,
  updateProject,
  updateProjectFile,
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

  it("sends the project prompt when updating project settings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "project-1", prompt: "默认使用中文。" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateProject("project-1", {
      name: "demo",
      test_command: null,
      build_command: null,
      ignored_names: ["node_modules"],
      prompt: "默认使用中文。",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          name: "demo",
          test_command: null,
          build_command: null,
          ignored_names: ["node_modules"],
          prompt: "默认使用中文。",
        }),
      }),
    );
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

  it("keeps and undoes a completed run", async () => {
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

    await keepRun("run-1");
    await undoRun("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/runs/run-1/keep",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/runs/run-1/undo",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("saves a project file into a pending run", async () => {
    const updateResponse = {
      file: { path: "src/main.js", content: "next", size: 4, language: "javascript" },
      run: { id: "run-1" },
      changes: { files: [], changed_files: 1, additions: 1, deletions: 1 },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(updateResponse), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateProjectFile("project-1", "src/main.js", "next", "before", "run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/project/file?project_id=project-1&path=src%2Fmain.js",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          content: "next",
          expected_content: "before",
          run_id: "run-1",
        }),
      }),
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

    await listSessions("project-1");
    await createSession("project-1");
    await getSession(session.id);
    await sendSessionMessage(session.id, "增加筛选功能", "auto", null, "task-draft-1", true);

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/sessions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ title: "新对话", project_id: "project-1" }),
      }),
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
          canvas_plan_mode: true,
          canvas: null,
          task_draft_id: "task-draft-1",
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

    await getProjectTree("project-1");
    await getProjectFile("project-1", "src/tasks file.js");
    await getRunTree("run-1");
    await getRunFile("run-1", "src/tasks file.js");
    await getRunChanges("run-1");
    await getRunFileDiff("run-1", "src/tasks file.js");

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/project/tree?project_id=project-1",
      "/api/project/file?project_id=project-1&path=src%2Ftasks+file.js",
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

    await expect(getProjectFile("project-1", "image.bin")).rejects.toThrow(
      "二进制文件不能作为文本查看",
    );
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

  it("registers, lists, activates, and creates projects", async () => {
    const project = { id: "project-1", name: "demo", root_path: "E:\\demo" };
    const payloads = [project, [project], project, project];
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(payloads.shift()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    await registerProject("E:\\demo");
    await listProjects();
    await activateProject("project-1");
    await createProject("E:\\projects", "new-app", "web");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/projects",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ path: "E:\\demo" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/projects/project-1/activate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/projects/create",
      expect.objectContaining({
        body: JSON.stringify({
          parent_path: "E:\\projects",
          name: "new-app",
          template: "web",
        }),
      }),
    );
  });
});
