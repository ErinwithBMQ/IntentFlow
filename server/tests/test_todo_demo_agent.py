import shutil
from pathlib import Path

import pytest

from app.agent.model_client import FakeModelClient
from app.agent.models import IntentBrief, IntentRequirement, ModelTurn, ToolCall
from app.agent.runner import AgentRunner
from app.agent.tools import ToolContext, ToolRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TODO_DEMO_ROOT = REPOSITORY_ROOT / "examples" / "todo-demo"


def tool_call(call_id: str, name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


async def test_agent_implements_and_verifies_todo_add_flow(tmp_path) -> None:
    node = shutil.which("node")
    vitest_cli = TODO_DEMO_ROOT / "node_modules" / "vitest" / "vitest.mjs"
    vite_cli = TODO_DEMO_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vitest_cli.is_file() or not vite_cli.is_file():
        pytest.skip("Todo integration test requires the initialized Node dependencies")

    workspace = tmp_path / "todo-demo"
    shutil.copytree(
        TODO_DEMO_ROOT,
        workspace,
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )

    old_import = (
        'import { countOpenTasks, createTaskElement, initialTasks } from "./tasks";'
    )
    new_import = (
        'import { countOpenTasks, createTask, createTaskElement, initialTasks } from "./tasks";'
    )
    old_main_setup = """const taskForm = document.querySelector("#task-form");

for (const task of initialTasks) {
  taskList.append(createTaskElement(task));
}

taskCount.textContent = `${countOpenTasks(initialTasks)} open`;

taskForm.addEventListener("submit", (event) => {
  event.preventDefault();
});"""
    new_main_setup = """const taskForm = document.querySelector("#task-form");
const taskInput = document.querySelector("#task-input");
const tasks = [...initialTasks];

for (const task of tasks) {
  taskList.append(createTaskElement(task));
}

taskCount.textContent = `${countOpenTasks(tasks)} open`;

taskForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const task = createTask(taskInput.value);

  if (!task) {
    taskInput.focus();
    return;
  }

  tasks.push(task);
  taskList.append(createTaskElement(task));
  taskCount.textContent = `${countOpenTasks(tasks)} open`;
  taskForm.reset();
  taskInput.focus();
});"""
    create_task_function = """

export function createTask(title, id = `task-${Date.now()}`) {
  const normalizedTitle = title.trim();
  if (!normalizedTitle) {
    return null;
  }

  return { id, title: normalizedTitle, completed: false };
}
"""
    old_test_import = 'import { countOpenTasks, initialTasks } from "./tasks";'
    new_test_import = 'import { countOpenTasks, createTask, initialTasks } from "./tasks";'
    count_open_test = """describe("countOpenTasks", () => {
  it("counts unfinished tasks", () => {
    expect(countOpenTasks(initialTasks)).toBe(2);
  });
});"""
    create_task_test = """

describe("createTask", () => {
  it("creates an unfinished task from trimmed input", () => {
    expect(createTask("  Ship the demo  ", "task-4")).toEqual({
      id: "task-4",
      title: "Ship the demo",
      completed: false,
    });
  });

  it("rejects empty input", () => {
    expect(createTask("   ")).toBeNull();
  });
});
"""
    demo_note = (
        '      <p class="demo-note">The add-task behavior is intentionally unfinished '
        "for the Agent demo.</p>\n"
    )

    turns = [
        ModelTurn(
            action="Inspect the Todo implementation",
            reason="Find the unfinished submit handler and existing behavior tests.",
            related_requirement_ids=["REQ-ADD"],
            tool_calls=[
                tool_call("read-main", "read_file", path="src/main.js"),
                tool_call("read-tasks", "read_file", path="src/tasks.js"),
                tool_call("read-tests", "read_file", path="src/tasks.test.js"),
            ],
        ),
        ModelTurn(
            action="Implement the add-task behavior and its tests",
            reason="Reuse the current task rendering and reject blank input.",
            related_requirement_ids=["REQ-ADD", "REQ-EMPTY"],
            tool_calls=[
                tool_call(
                    "patch-task-helper",
                    "apply_patch",
                    path="src/tasks.js",
                    old_text="\nexport function createTaskElement(task) {",
                    new_text=create_task_function + "\nexport function createTaskElement(task) {",
                ),
                tool_call(
                    "patch-main-import",
                    "apply_patch",
                    path="src/main.js",
                    old_text=old_import,
                    new_text=new_import,
                ),
                tool_call(
                    "patch-main-handler",
                    "apply_patch",
                    path="src/main.js",
                    old_text=old_main_setup,
                    new_text=new_main_setup,
                ),
                tool_call(
                    "patch-test-import",
                    "apply_patch",
                    path="src/tasks.test.js",
                    old_text=old_test_import,
                    new_text=new_test_import,
                ),
                tool_call(
                    "patch-tests",
                    "apply_patch",
                    path="src/tasks.test.js",
                    old_text=count_open_test,
                    new_text=count_open_test + create_task_test,
                ),
                tool_call(
                    "remove-demo-note",
                    "apply_patch",
                    path="index.html",
                    old_text=demo_note,
                    new_text="",
                ),
            ],
        ),
        ModelTurn(
            action="Run behavior tests and production build",
            reason="Both behavior and syntax need executable evidence.",
            related_requirement_ids=["REQ-ADD", "REQ-EMPTY"],
            tool_calls=[
                tool_call("run-tests", "run_command", command="test"),
                tool_call("run-build", "run_command", command="build"),
            ],
        ),
        ModelTurn(
            action="Report the verified Todo change",
            reason="The automated tests and production build both passed.",
            related_requirement_ids=["REQ-ADD", "REQ-EMPTY"],
            tool_calls=[
                tool_call(
                    "report",
                    "report_result",
                    status="completed",
                    summary="Todo add-task flow implemented and verified.",
                    evidence=["Vitest passed", "Vite production build passed"],
                )
            ],
        ),
    ]
    intent = IntentBrief(
        title="Complete the Todo add-task flow",
        goal="Users can add a non-empty task and immediately see the updated open count.",
        requirements=[
            IntentRequirement(
                id="REQ-ADD",
                description="Submitting text creates an unfinished task.",
                acceptance_criteria=["A new task is rendered", "The open count increases"],
                source_ids=["idea-add-task"],
            ),
            IntentRequirement(
                id="REQ-EMPTY",
                description="Blank input does not create a task.",
                acceptance_criteria=["Whitespace-only input is rejected"],
                source_ids=["note-empty-input"],
            ),
        ],
        constraints=["Keep the existing visual style"],
    )
    context = ToolContext(
        workspace,
        allowed_commands={
            "test": (node, str(vitest_cli), "run", "--root", str(workspace)),
            "build": (node, str(vite_cli), "build", str(workspace)),
        },
    )

    result = await AgentRunner(FakeModelClient(turns), ToolRegistry(), context).run(intent)

    assert result.status == "completed"
    assert result.steps == 4
    assert "createTask(taskInput.value)" in (workspace / "src" / "main.js").read_text(
        encoding="utf-8"
    )
    command_events = [
        event
        for event in result.events
        if event.kind == "tool_finished" and event.tool_name == "run_command"
    ]
    assert [event.status for event in command_events] == ["succeeded", "succeeded"]
    assert result.report.evidence == ["test exited with code 0", "build exited with code 0"]
