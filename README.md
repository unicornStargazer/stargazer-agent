# Stargazer Agent

Stargazer Agent 由 **Python 后端 + Vue/TypeScript 前端**组成。后端使用 FastAPI 提供 HTTP/SSE 接口，使用 SQLite 保存会话与请求状态，通过 OpenAI 兼容的 `/chat/completions` 接口调用模型；前端提供浏览器聊天工作台。

当前支持连续文本对话、模型 Profile 切换、流式正文与公开 reasoning、Token 用量、请求幂等，以及有界的 Agent/Tool 循环。业务 Skill 使用渐进式披露：先提供目录摘要，再按需激活正文和读取单份资源。默认只注册受限的 Skill 工具，不提供任意文件读取、Shell 或脚本执行能力；尚未接入 Dokkan 数据服务。

## 环境与安装

- Python 3.12+、[uv](https://docs.astral.sh/uv/)
- Node.js 20.19+，推荐 Node.js 22 LTS，以及 npm（用于 Vue/TypeScript 前端）

在仓库根目录执行：

```powershell
npm install
uv sync --project backend --locked
```

Python 依赖环境位于 `backend/.venv`。Node.js 不再用于运行后端。

## 配置

Python 默认读取仓库根目录的 `config/stargazer-agent.json`。已有配置可继续使用，不要用示例覆盖自己的密钥或数据库路径。首次配置请参照 [服务端配置](docs/configuration.md) 创建文件，填写 `provider.apiKey`、`provider.baseUrl` 与 `agents.profiles`，默认监听地址使用 `127.0.0.1:3000`。

模型、密钥、端口、数据库路径和 Skill 目录均来自 JSON，不读取旧的 `OPENAI_*`、`HOST`、`PORT` 或 `STARGAZER_*` 环境变量。相对配置路径、`storage.databasePath` 和 `skillsDirectory` 都以**仓库根目录**为基准，而非启动命令所在目录。

注意旧根示例中的 `examples/skills` 仍是历史 TS 格式，不能直接作为 Python Skill 目录。可省略 `skillsDirectory`，或使用 `backend/examples/skills` 验证演示 Skill；格式见 [业务 Skill](docs/skills.md)。真实配置不要提交到 Git。

## 启动 Web 工作台

### 前后端开发

在仓库根目录执行：

```powershell
npm run web:dev
```

该命令通过 concurrently 同时运行 `npm run start:server`（Python API）和 Vite。浏览器访问 `http://127.0.0.1:5173`；Vue 组件支持热更新，Vite 将 `/api` 代理到 `http://127.0.0.1:3000`。配合该命令时，请保持 JSON 中 `server.port` 为 `3000`。

### 单端口构建页面

```powershell
npm run web
```

该命令先执行 `build:web` 生成 `web/dist`，再运行 `npm start` 启动 Python，页面与 API 同源。使用默认端口配置时访问 `http://127.0.0.1:3000`。

也可以拆开执行：

```powershell
npm run build
npm start
```

`build` 仅构建前端，不编译旧 TS 后端。`dev` 调用 `web:dev`，同时启动 Python API 与 Vite，不是旧 CLI。`start` 和 `start:server` 执行以下 Python 启动命令，不表示 Python 自动重载：

```powershell
uv run --project backend --locked python -m dokkan_agent.main
```

需要独立开发配置时，可使用 [后端 README](backend/README.md) 中的 `--config backend/config/local.json` 流程。该开发示例监听 **3001**，使用独立数据库；它不会自动改变 Vite 的 **3000** 代理，应先构建前端并访问 3001 上的同源页面。

启动会初始化配置指定的 SQLite 数据库，但不会主动探测远程模型。用户发送消息后才可能产生模型请求与费用。

## 模型、Skill 与 Tool

- 模型列表来自 `agents.profiles`，浏览器只获取 `id/name/model` 安全摘要。切换模型保留当前会话与历史，见 [模型切换](docs/model-switching.md)。
- Skill 由 JSON 的 `skillsDirectory` 指定，全局独立于模型，不生成模型 Profile。每条消息先提供 L1 摘要，按需加载 L2 正文和 L3 资源，见 [业务 Skill](docs/skills.md)。
- 正式注册工具为 `activate_skill` 和 `read_skill_resource`；`echo_text` 仅是演示/测试扩展示例，见 [Tool 扩展](docs/tools.md)。Skill 元数据不能授予工具权限。

旧 TypeScript 后端的 `chat` CLI 不再是当前支持入口；不要使用 `npm run dev -- chat ...` 或 `node dist/cli.js`。

## 检查与测试

在仓库根目录执行前端检查：

```powershell
npm run typecheck
npm test
npm run build:web
```

`npm test` 和 `npm run typecheck` 仅覆盖 Vue/TypeScript 前端，不验证 Python 后端。后端检查在 `backend` 目录执行：

```powershell
cd backend
uv run --locked ruff check .
uv run --locked python scripts/check_code_style.py
uv run --locked mypy
uv run --locked pytest -q
uv build
```

后端自动测试使用脱敏示例、模拟模型响应和临时 SQLite，不需要真实密钥或付费模型请求。更多说明见 [后端验证](backend/README.md#验证)。

## 项目结构

```text
backend/
├── src/dokkan_agent/
│   ├── main.py          Python 服务入口
│   ├── bootstrap/       JSON 配置、路径基准与依赖装配
│   ├── interfaces/http/ FastAPI 路由、校验、SSE 与静态页面
│   ├── domain/          Agent、会话、Skill、Tool 契约
│   ├── application/     会话用例与有界 AgentRunner
│   └── infrastructure/  Provider、SQLite、Skill 与 Tool 适配
├── tests/               Python 单元、契约与架构测试
├── config/              脱敏开发配置示例
└── docs/                当前后端设计与运行契约
web/
├── vite.config.ts       Vue 构建与开发 API 代理
└── src/                 Vue 组件、Pinia 状态与 HTTP/SSE 客户端
config/                  默认服务端 JSON 配置位置
```

旧根 `src/`、`test/`、`tsconfig.json`、`tsconfig.build.json` 和 `vitest.config.ts` 不再作为当前后端源码、测试或构建入口；前端仍保留 Vue/TypeScript 工具链。

## 文档与运行边界

当前后端请从 [后端 README](backend/README.md)、[HTTP 运行流程](backend/docs/http-runtime.md)、[Agent 内核](backend/docs/runtime-core.md)、[HTTP 契约](backend/docs/http-contract.md) 和 [存储契约](backend/docs/storage-contract.md) 阅读。`docs/backend-architecture.md` 与 `docs/backend-runtime-flow.md` 保留为旧 TS 后端历史归档，不能作为当前启动指南。

当前部署为单进程、单 worker SQLite，不提供跨进程锁或用户账号隔离。模型与工具调用在数据库事务外执行；完整回答提交成功后才发送 SSE `done`。升级已有数据库前应先停写并做一致备份，不提供自动降级或旧 TS 后端回退保证。
