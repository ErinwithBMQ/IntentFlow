# IntentFlow

IntentFlow 是一个轻量编程 Agent 工具：用户自由表达 Web 功能想法，AI 将其整理、实现并验证。

当前已形成对话优先的最小闭环：用户在持续 Session 中直接与统一 Agent 对话，Agent 根据
本轮要求选择回答、整理计划或启动执行。用户可按需附加 Canvas，并查看实时执行、逐需求证据、
代码、Diff 以及应用或放弃结果。

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
```

仅在使用仓库内置 Todo 示例时，才需要进入 `examples\todo-demo` 执行 `npm install`。

## 启动 IntentFlow

```powershell
.\scripts\dev.ps1
```

前端默认运行在 `http://localhost:5173`，后端默认运行在 `http://localhost:8000`。

首次进入且没有已登记项目时，点击“打开文件夹选择器”会由本机后端打开系统目录窗口；也可以
手动输入绝对路径。项目授权记录保存在 SQLite 中，后续会恢复最近项目。顶部项目选择器可以
切换已登记项目；每个 Session 固定属于创建时的项目，消息或 Agent 仍在处理时不能切换。
“项目设置”可调整显示名称、`test`/`build` 受控命令参数和忽略目录。命令参数每行填写一个，
`{workspace}` 表示 Agent 隔离目录，配置不会经过 Shell 执行。

项目管理也可以在指定父目录下创建空项目或无外部依赖的原生 Web 模板。主工作区会优先预览
Agent 生成的 `dist/index.html`；纯静态项目也可直接预览根目录 `index.html`。没有网页入口的
项目不会显示“预览”标签。

在右侧输入框中直接描述问题、规划请求或修改要求。统一 Agent 会在内部选择直接回答、返回
结构化计划或生成 IntentBrief 并启动隔离运行，不再要求用户预先切换 Ask、Plan、Agent。
“附加 Canvas”会保存发送瞬间的不可变画布快照；当前消息始终是主要指令，Canvas 只是附件，
不会因为附件中存在需求就自动执行。

输入框旁的权限选项独立控制工具执行：“请求批准”会在修改前暂停，“自动允许”会在当前
Session 的后续 Run 中自动允许受控修改。两者都不能绕过工作区、路径和命令白名单，也不会
自动把结果写回项目当前版本。

消息发送后，输入框右侧的发送按钮会变成中断按钮：理解需求或整理计划时会取消当前模型请求，
Agent Run 已启动时会停止 Runner。中断只停止当前处理，不会删除既有对话和历史 Diff。
没有可用自动化测试的实现可以正常结束，但会明确标记为未验证。已结束的 Run 即使未验证、
失败或中断，用户仍可检查代码和 Diff，并在风险提示后二次确认是否写回项目当前版本。
每次 Agent 运行都会把当前 Session 所属项目复制到
`runtime-data/runs/<运行ID>/workspace`，未经“应用到项目”不会修改项目当前版本。

Agent 调用 `apply_patch` 前会展示目标文件、修改原因和真实 Patch，并暂停等待“允许一次”、
“本轮自动允许”或“拒绝”。拒绝结果会返回 Agent 供其调整；等待期间可以停止运行。
这里的工具审批只决定能否修改隔离副本，运行结束后仍需单独点击“应用到项目”或“放弃修改”。

Session、消息、Canvas 快照和 Run 快照保存在 `runtime-data/intentflow.db`。刷新页面或重启
服务后可以恢复历史；服务重启时尚未结束的旧 Run 会被标记为已停止，不会伪装成仍在执行。
同一 Session 的上一轮 Agent Run 必须先“应用到项目”或“放弃修改”，才能启动下一轮；
待审查期间仍可继续提问、解释结果或整理计划。
AI 回复支持安全的 Markdown 与 GFM 渲染，包括标题、列表、链接、代码块和表格；原始 HTML
不会执行。对话标题旁的删除按钮会删除该 Session 的消息、Canvas 快照、Run 记录和隔离副本，
但不会修改项目当前版本；运行中的会话必须先停止。

Agent 最终报告会为每项需求展示“已验证、已实现、失败或未解决”状态。状态由 Runner
根据实际修改文件和关联的测试或构建记录判定；模型声明本身不能生成“已验证”。

## 自研 Agent Harness

Agent 核心循环、工具协议、审批和上下文管理均由项目自行实现，没有引入 Agent 框架。
`SessionContextBuilder` 会在每条消息处理前生成统一的 `ContextEnvelope`，其中包含当前请求、
近期对话、较早摘要、权限策略，以及 Run 的运行状态、审批、验证和最终应用/放弃事实。
这些数据库事实优先于聊天文字，因此普通问答也能准确知道上一轮修改最终是否进入项目。

`ContextManager` 在每次模型调用前生成有预算的上下文视图：完整的标准化模型动作和工具结果
仍保存在 Run 快照中用于审计，较早回合可被摘要，长工具输出只在模型视图中裁剪。当前目标、
约束、执行进度、修改文件、有效验证、审批决定和未解决问题会进入结构化 checkpoint。

checkpoint、逐轮上下文指标和审计历史随 Run 一起写入 SQLite。服务重启不会恢复旧协程或
待审批动作，但会保留这些事实；同一 Session 的新 Run 只接收近期对话及已经应用或放弃的
审查结果。模型超时、限流和临时网络错误会有限重试，配置错误和用户拒绝不会自动重试。

可在根目录 `.env` 调整以下预算：

```dotenv
AGENT_CONTEXT_WINDOW_TOKENS=64000
AGENT_CONTEXT_RESERVE_TOKENS=8000
AGENT_CONTEXT_KEEP_RECENT_TOKENS=12000
AGENT_CONTEXT_COMPACT_AT_RATIO=0.8
AGENT_CONTEXT_MAX_TOOL_OUTPUT_CHARACTERS=12000
```

固定评测任务和结果格式见 `server/evals/`。真实模型对照必须记录相同的模型、端点、任务版本
和预算，并区分真实运行结果与 FakeModel/单元测试结果。

## 检查

```powershell
cd web
npm test
npm run lint
npm run build

cd ..\server
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .

# 可选：验证仓库内置 Todo 示例
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
