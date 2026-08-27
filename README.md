# IntentFlow

IntentFlow 是一个轻量编程 Agent 工具：用户自由表达 Web 功能想法，AI 将其整理、实现并验证。

当前已完成阶段 1 的 Agent Runtime：包含受控本地工具、运行事件、终止规则、
FakeModel 闭环和 OpenAI Responses 模型适配层。前端目前仍是运行骨架。

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
