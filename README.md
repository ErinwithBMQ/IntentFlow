# IntentFlow

IntentFlow 是一个面向 Web 项目的本地编程 Agent。用户可以直接用自然语言描述需求，Agent 会理解任务、规划方案、修改代码并执行验证；整个过程中，用户都可以查看项目文件、执行状态和真实 Diff，并决定是否保留本轮修改。

## 核心功能

- **自然语言驱动开发**：在持续对话中提出问题、规划功能或直接发起代码修改。
- **Canvas 可视化规划**：将目标、任务和约束整理为可编辑画布，确认后再交给 Agent 执行。
- **IDE 式项目工作区**：浏览项目结构、查看和编辑代码，并预览可运行的 Web 页面。
- **实时 Agent 执行**：展示任务进度、工具调用、验证结果和最终报告。
- **代码修改审批**：Agent 写入代码前展示目标文件、修改原因和 Patch，由用户决定是否允许。
- **真实 Diff 审查**：基于项目文件生成增删对比，清晰展示每一处代码变化。
- **保留或撤销修改**：运行结束后由用户最终决定保留成果，或撤销本轮全部改动。
- **会话与项目管理**：支持多个本地项目，并持久化会话、Canvas、运行记录和模型配置。

## 项目亮点

- **自研 Agent Harness**：Agent 循环、工具协议、上下文管理、审批和验证流程均由项目自行实现，未引入现成 Agent 框架。
- **用户始终掌握修改权**：写入前有工具审批，执行后还有保留或撤销确认，AI 不会替用户完成最终决策。
- **以真实文件为准**：项目结构、代码内容和 Diff 均由后端读取文件系统生成，不依赖模型描述或前端日志推断。
- **明确区分实现与验证**：分别呈现未配置验证、命令无法启动、验证失败和验证通过，避免将“已实现”误报为“已验证”。
- **对话、规划与执行一体化**：同一个 Agent 根据用户意图选择直接回答、生成 Canvas 计划或启动代码执行，无需频繁切换工作模式。

## 技术栈

- 前端：React 19、TypeScript、Vite、React Flow
- 后端：Python 3.11、FastAPI、Pydantic、SQLite
- 模型接口：OpenAI Responses API 兼容服务

## 示例项目

`examples/todo-demo` 是一个独立的原生 Todo Web 项目，用于快速体验和演示 IntentFlow 的完整工作流，例如让 Agent 修改功能、运行测试与构建、查看 Diff，以及保留或撤销结果。它不是 IntentFlow 前后端本身的依赖，不使用该示例时无需安装其中的依赖。

如需使用该示例，在 `examples/todo-demo` 目录执行 `npm install`，然后在 IntentFlow 中将该目录作为本地项目打开。

## 启动项目

### 1. 环境要求

- Node.js 22+
- npm 10+
- Python 3.11+

### 2. 安装依赖

```powershell
cd web
npm install

cd ..\server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 3. 配置模型

启动后可在页面的“模型配置”中填写 API URL、API Key 和模型名称；也可以复制根目录的 `.env.example` 为 `.env` 并填写：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=your_api_url
OPENAI_MODEL=your_model
```

模型服务需要兼容 OpenAI Responses API。

### 4. 启动前后端

在项目根目录执行：

```powershell
.\scripts\dev.ps1
```

启动后访问：

- 前端：`http://localhost:5173`
- 后端：`http://localhost:8000`

进入页面后，选择一个本地项目目录，即可开始对话、规划和执行任务。
