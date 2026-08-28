# IntentFlow

IntentFlow 是一个轻量编程 Agent 工具：用户自由表达 Web 功能想法，AI 将其整理、实现并验证。

当前已完成阶段 3 的最小链路：自由便签画布、真实模型 IntentBrief 编译、运行 Agent、
实时事件时间线、停止任务，以及逐需求文件和测试证据展示。

## 环境要求

- Node.js 22+
- npm 10+
- Python 3.11+

## 初始化

```powershell
cd web
npm install

cd ..\server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

cd ..\examples\todo-demo
npm install
```

## 启动 IntentFlow

```powershell
.\scripts\dev.ps1
```

前端默认运行在 `http://localhost:5173`，后端默认运行在 `http://localhost:8000`。

在画布中整理出 IntentBrief 后，点击“运行 Agent”。每次运行都会把
`examples/todo-demo` 复制到 `runtime-data/runs/<运行ID>/todo-demo`，Agent 只修改副本。
原始 Todo 示例不会被改变，可以重复演示。

“整理意图”默认调用真实模型。AI 编译失败时不会自动运行或静默降级；界面会显示错误，
用户可主动点击“使用本地规则整理”，并在结果中看到明确的降级标识。

Agent 最终报告会为每项需求展示“已验证、已实现、失败或未解决”状态。状态由 Runner
根据实际修改文件和关联的测试或构建记录判定；模型声明本身不能生成“已验证”。

## 检查

```powershell
cd web
npm test
npm run lint
npm run build

cd ..\server
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .

cd ..\examples\todo-demo
npm test
npm run build
```

真实 `.env`、API Key 和 `runtime-data/` 不得提交到仓库。

## 真实模型冒烟测试

在根目录 `.env` 配置模型后执行：

```powershell
cd server
.\.venv\Scripts\python.exe -u scripts\smoke_real_agent.py
```

脚本只修改 `runtime-data/real-agent-smoke/` 下的 Todo 临时副本，并输出每一步动作、
原因、结果和最终验证证据，不会修改原始示例项目。

Intent Compiler 的无连线便签、纯文字和矛盾输入场景可单独执行：

```powershell
cd server
.\.venv\Scripts\python.exe -u scripts\smoke_real_intent_compiler.py
```

当前模型适配层使用 OpenAI Responses API。`OPENAI_BASE_URL` 必须指向兼容 Responses
协议的服务地址；Anthropic 协议地址不能直接使用，否则会返回 404。
