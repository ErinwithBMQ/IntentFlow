import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

from app.agent.model_client import OpenAIResponsesModelClient
from app.agent.models import IntentBrief, IntentRequirement, RunEvent
from app.agent.runner import AgentRunner
from app.agent.tools import ToolContext, ToolRegistry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TODO_DEMO_ROOT = REPOSITORY_ROOT / "examples" / "todo-demo"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def required_config(config: dict[str, str | None], name: str) -> str:
    value = config.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing {name} in {REPOSITORY_ROOT / '.env'}")
    return value.strip()


async def print_event(event: RunEvent) -> None:
    target = f" -> {event.target}" if event.target else ""
    print(f"[{event.sequence:02d}] {event.status:<9} {event.action}{target}")
    print(f"     原因: {event.reason}")


async def run_smoke_test() -> int:
    config = dotenv_values(REPOSITORY_ROOT / ".env")
    api_key = required_config(config, "OPENAI_API_KEY")
    model = required_config(config, "OPENAI_MODEL")
    base_url = (config.get("OPENAI_BASE_URL") or "").strip() or None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = REPOSITORY_ROOT / "runtime-data" / "real-agent-smoke" / timestamp
    workspace = run_root / "todo-demo"
    run_root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(
        TODO_DEMO_ROOT,
        workspace,
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )

    node = shutil.which("node")
    vitest_cli = TODO_DEMO_ROOT / "node_modules" / "vitest" / "vitest.mjs"
    vite_cli = TODO_DEMO_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vitest_cli.is_file() or not vite_cli.is_file():
        raise RuntimeError("Todo Node dependencies are not initialized")

    intent = IntentBrief(
        title="完成 Todo 添加任务流程",
        goal="用户提交非空文本后，页面立即显示新任务并更新未完成任务数量。",
        requirements=[
            IntentRequirement(
                id="REQ-ADD",
                description="提交非空文本会创建并渲染一条未完成任务。",
                acceptance_criteria=["新任务出现在列表中", "未完成数量增加"],
                source_ids=["idea-add-task"],
            ),
            IntentRequirement(
                id="REQ-EMPTY",
                description="空白输入不能创建任务。",
                acceptance_criteria=["纯空格输入不会改变任务列表"],
                source_ids=["note-empty-input"],
            ),
        ],
        constraints=["保持当前视觉风格", "为核心行为补充自动化测试"],
    )
    registry = ToolRegistry()
    model_client = OpenAIResponsesModelClient(
        registry,
        model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=120.0,
    )
    context = ToolContext(
        workspace,
        allowed_commands={
            "test": (node, str(vitest_cli), "run", "--root", str(workspace)),
            "build": (node, str(vite_cli), "build", str(workspace)),
        },
    )
    runner = AgentRunner(
        model_client,
        registry,
        context,
        max_steps=8,
        event_sink=print_event,
    )

    print(f"模型: {model}")
    print(f"临时工作区: {workspace}")
    result = await runner.run(intent)
    result_path = run_root / "run-result.json"
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"\n最终状态: {result.status}")
    print(f"结果记录: {result_path}")
    for evidence in result.report.evidence:
        print(f"验证证据: {evidence}")
    for unresolved in result.report.unresolved:
        print(f"未解决: {unresolved}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_smoke_test()))
