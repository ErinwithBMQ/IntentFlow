# IntentFlow

IntentFlow 是一个轻量编程 Agent 工具：用户自由表达 Web 功能想法，AI 将其整理、实现并验证。

当前已形成对话优先的最小闭环：用户在持续 Session 中直接与统一 Agent 对话，Agent 根据
本轮要求选择回答、整理计划或启动执行。用户可按需附加 Canvas，并查看实时执行、代码、Diff
以及保留或撤销结果；任务拆解、逐需求证据和原始工具记录按需展开。

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
`{workspace}` 表示当前项目目录，配置不会经过 Shell 执行。

项目管理也可以在指定父目录下创建空项目或无外部依赖的原生 Web 模板。主工作区会优先预览
Agent 生成的 `dist/index.html`；纯静态项目也可直接预览根目录 `index.html`。没有网页入口的
项目不会显示“预览”标签。

在右侧输入框中直接描述问题、规划请求或修改要求。统一 Agent 会在内部选择直接回答、返回
结构化计划或生成 IntentBrief 并启动 Agent Run，不再要求用户预先切换 Ask、Plan、Agent。
“附加 Canvas”会保存发送瞬间的不可变画布快照；当前消息始终是主要指令，Canvas 只是附件，
不会因为附件中存在需求就自动执行。

输入框旁的权限选项独立控制工具执行：“请求批准”会在修改前暂停，“自动允许”会在当前
Session 的后续 Run 中自动允许受控修改。两者都不能绕过工作区、路径和命令白名单，也不会
跳过本轮结束后的保留或撤销决定。

消息发送后，输入框右侧的发送按钮会变成中断按钮：理解需求或整理计划时会取消当前模型请求，
Agent Run 已启动时会停止 Runner。中断只停止当前处理，不会删除既有对话和历史 Diff。
没有可用自动化测试的实现可以正常结束，但会明确标记为未验证。已结束的 Run 即使未验证、
失败或中断，用户仍可检查代码和 Diff，并决定保留当前修改或撤销本轮。
验证工具会结构化区分“未配置验证”“命令无法启动”“验证失败”和“验证通过”；前两种结果
会提示 Agent 不要原样重复命令，也不会被误报成代码测试失败。
Agent 经批准后直接修改当前项目；系统只在 `runtime-data/runs/<运行ID>/checkpoint` 中保存
本轮实际触碰文件的修改前和修改后快照，不再复制完整项目。

“代码”标签页支持直接编辑现有 UTF-8 文本文件并保留语法高亮，停止输入后会自动保存，`Ctrl+Z` 可按编辑历史
撤销。若当前存在待审查 Run，自动保存会并入该轮 Checkpoint、立即刷新 Diff，并将此前验证
标记为失效；没有待审查 Run 时，保存会直接写入当前项目。代码与 Diff 使用项目内置的
JetBrains Mono 字体，不依赖本机字体安装。

Agent 调用 `apply_patch` 前会展示目标文件、修改原因和真实 Patch，并暂停等待“允许一次”、
“本轮自动允许”或“拒绝”。拒绝结果会返回 Agent 供其调整；等待期间可以停止运行。
工具审批决定能否写入当前项目；运行结束后可选择“保留修改”或通过 Checkpoint“撤销本轮”。

Session、消息、Canvas 快照和 Run 快照保存在 `runtime-data/intentflow.db`。刷新页面或重启
服务后可以恢复历史；服务重启时尚未结束的旧 Run 会被标记为已停止，不会伪装成仍在执行。
同一 Session 的上一轮 Agent Run 必须先“保留修改”或“撤销本轮”，才能启动下一轮；
待审查期间仍可继续提问、解释结果或整理计划。
AI 回复支持安全的 Markdown 与 GFM 渲染，包括标题、列表、链接、代码块和表格；原始 HTML
不会执行。删除对话时，待审查的直接工作区修改会先安全撤销，再删除该 Session 的消息、
Canvas 快照、Run 记录和 Checkpoint；已保留的项目修改不会被删除。运行中的会话必须先停止。

Agent 最终报告默认只展示整体完成状态、验证状态和文件变更数量，完整总结与逐需求结论采用
渐进披露，可继续展开相关文件和证据。每项需求的“已验证、已实现、失败或未解决”状态由 Runner
根据实际修改文件和关联的测试或构建记录判定；模型声明本身不能生成“已验证”。

## 自研 Agent Harness

Agent 核心循环、工具协议、审批和上下文管理均由项目自行实现，没有引入 Agent 框架。
`SessionContextBuilder` 会在每条消息处理前生成统一的 `ContextEnvelope`，其中包含当前请求、
近期对话、较早摘要、权限策略，以及 Run 的运行状态、审批、验证和最终保留/撤销事实。
这些数据库事实优先于聊天文字，因此普通问答也能准确知道上一轮修改最终是否被保留。

`ContextManager` 在每次模型调用前生成有预算的上下文视图：完整的标准化模型动作和工具结果
仍保存在 Run 快照中用于审计，较早回合可被摘要，长工具输出只在模型视图中裁剪。当前目标、
约束、执行进度、修改文件、有效验证、审批决定和未解决问题会进入结构化 checkpoint。

checkpoint、逐轮上下文指标和审计历史随 Run 一起写入 SQLite。服务重启不会恢复旧协程或
待审批动作，但会保留这些事实；同一 Session 的新 Run 只接收近期对话及已经保留或撤销的
审查结果。模型超时、限流和临时网络错误会有限重试，配置错误和用户拒绝不会自动重试。
单个 Run 默认最多进行 20 轮模型调用；达到上限仍未提交 `report_result` 时会明确失败，测试
或特殊入口仍可注入更低的轮数预算。

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
