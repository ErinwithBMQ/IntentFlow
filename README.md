# IntentFlow

IntentFlow 是一个轻量编程 Agent 工具：用户自由表达 Web 功能想法，AI 将其整理、实现并验证。

当前已形成对话优先的最小闭环：用户可在持续 Session 中使用 Ask、Plan 或 Agent 模式，
按需附加 Canvas，并查看实时执行、逐需求证据、代码、Diff 以及接受或放弃结果。

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

在右侧输入框中直接描述需求：Ask 可以只读查看项目并回答问题，Plan 可以结合现有代码整理
结构化计划，但二者都不能修改文件或运行命令；Agent 会在内部生成 IntentBrief 并启动隔离
运行。“附加 Canvas”会保存发送瞬间的不可变画布快照。
当前消息始终是主要指令，Canvas 只是附件；问候、闲聊或没有明确工程动作的 Agent 消息
只会得到回复，不会因为附件中存在需求便自动启动 Run。
Ask 和 Plan 当前读取的是受大小限制的项目快照；更大项目的按需搜索与上下文压缩将在
ContextManager 阶段替换这一基础实现。
Plan 会先区分“普通问题”和“规划请求”：普通问题直接回答，只有明确要求设计或拆解改动时
才生成结构化 IntentBrief，避免把简单提问硬凑成需求清单。
每次 Agent 运行都会把 `examples/todo-demo` 复制到
`runtime-data/runs/<运行ID>/todo-demo`，未经“接受全部”不会修改项目当前版本。

Session、消息、Canvas 快照和 Run 快照保存在 `runtime-data/intentflow.db`。刷新页面或重启
服务后可以恢复历史；服务重启时尚未结束的旧 Run 会被标记为已停止，不会伪装成仍在执行。
同一 Session 的上一轮 Agent Run 必须先“应用到项目”或“放弃修改”，才能启动下一轮；
待审查期间仍可继续使用 Ask 和 Plan。
AI 回复支持安全的 Markdown 与 GFM 渲染，包括标题、列表、链接、代码块和表格；原始 HTML
不会执行。对话标题旁的删除按钮会删除该 Session 的消息、Canvas 快照、Run 记录和隔离副本，
但不会修改项目当前版本；运行中的会话必须先停止。

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
