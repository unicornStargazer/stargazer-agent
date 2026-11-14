# Python Agent 后端

当前默认后端为 Python：提供 Skill 渐进式披露、Tool 注册、有界 AgentRunner、SQLite 会话与请求幂等、OpenAI 兼容模型流和 FastAPI 聊天接口。Vue/TypeScript 前端继续保留；根 npm 的 `start`、`start:server` 启动 Python，`dev` 调用 `web:dev` 同时启动 Python 与 Vite，`build` 只构建前端。Dokkan 数据服务暂不接入。

## 入口与启动

需要 Python 3.12+ 和 uv。在仓库根目录执行默认启动：

```powershell
uv sync --project backend --locked
npm start
# 等价的 Python 入口：
# uv run --project backend --locked python -m dokkan_agent.main
```

默认配置为 `config/stargazer-agent.json`，端口沿用 3000；已有文件不要覆盖。配置中的旧 TS Skill 目录需按 [配置文档](../docs/configuration.md) 调整为兼容目录或省略。前端开发使用 `npm run dev` 或 `npm run web:dev`，同时启动 Python 与 Vite；单端口页面使用 `npm run web` 先构建再启动。

需要使用 3001 和独立数据库验证时，从仓库根目录切换到 backend：

```powershell
cd D:\stargazer-agent\backend
uv sync --locked
Copy-Item config/development.example.json config/local.json
# 编辑 config/local.json，填写 provider.apiKey、provider.baseUrl 和 agents.profiles 中的 model。
uv run --locked python -m dokkan_agent.main --config backend/config/local.json
```

先在仓库根运行 `npm run build:web`，再启动后端，浏览器打开 `http://127.0.0.1:3001` 即可使用同源页面和 `/api`。配置复制只需首次执行，已有 local.json 时直接编辑，避免覆盖自己的配置。示例使用明确标记的演示 Skill，不代表正式 Dokkan Skill。

启动会创建并迁移配置指定的 `backend/data/development.sqlite`，不主动发送模型请求；用户发消息后才调用模型。`--config` 相对路径以**仓库根目录**为基准，省略时读取现有 `config/stargazer-agent.json`。迁移验证期间务必使用独立配置和数据库，避免其他进程同时写实际会话库。本地配置已忽略，不要把真实密钥放入示例。

工程依赖位于 `backend/.venv`，不用仓库旧 `.venv`。开发网络直连 PyPI 曾超时，因此 `pyproject.toml` 显式使用清华 PyPI 镜像，`uv.lock` 记录确切版本、下载来源与哈希；没有以环境变量覆盖应用配置。

源码运行时自动定位仓库根目录；如果独立安装 wheel，需通过 `--project-root D:\stargazer-agent` 显式指定配置和数据的根目录，不能把安装目录或启动目录误当成项目目录。

调试器选择 `backend/.venv/Scripts/python.exe`，启动模块为 `dokkan_agent.main`，参数与上面相同。可依次断点：

1. `src/dokkan_agent/main.py::main`：进程入口，解析配置路径并启动 Uvicorn。
2. `src/dokkan_agent/bootstrap/application.py::create_app`：组合根，读取配置并创建应用。
3. `src/dokkan_agent/interfaces/http/app.py::create_http_app`：注册 HTTP 路由与生命周期。
4. `src/dokkan_agent/interfaces/http/routes.py::stream_chat`：Web 流式请求入口。
5. `src/dokkan_agent/application/conversation/service.py::ConversationService.prepare`：会话锁、去重和模型选择。
6. `src/dokkan_agent/application/runtime/runner.py::AgentRunner.stream`：模型/工具循环。

启动成功后 `/health/live`、`/health/ready` 都返回 200；就绪表示配置、Skill 和数据库已初始化，不代表远程模型实时可用。没有隐含的付费模型探测。

现有 5173 Vite 代理保持指向 3000，与默认 Python 配置对接；独立开发示例仍使用 3001，应访问 3001 上的构建页面验证。若要用该独立配置配合 Vite，需将其 `server.port` 设为 3000，并用显式 `--config` 单独启动 Python，再启动 Vite；不要同时启动两个占用 3000 的服务。当前仅支持单 worker，不提供多进程并发保证。

## 职责与依赖

| 目录                                    | 职责                                        | 依赖边界                            |
| --------------------------------------- | ------------------------------------------- | ----------------------------------- |
| `bootstrap`                             | 文件配置、路径基准、应用装配                | 组合根可以依赖各层                  |
| `interfaces/http`                       | HTTP DTO、SSE 编码、路由                    | 不直连 SQLite/Provider              |
| `domain/agent`                          | 模型消息、流事件、ModelGateway              | 仅标准库和其他领域契约              |
| `domain/conversation`                   | 请求身份、完整轮次、请求状态                | 不含 HTTP 或锁实现                  |
| `domain/skill`                          | L1 描述、L2 激活、L3 单资源契约             | 不访问磁盘，不绑定模型              |
| `domain/tool`                           | 完整调用、注册定义、成功/失败结果           | 不执行文件或脚本                    |
| `application/runtime`                   | ContextBuilder、AgentRunner、预算和事件聚合 | 每条消息独立 RunContext，不负责落库 |
| `application/skill`、`application/tool` | Skill/Tool 用例编排和注册                   | 不直接访问文件、HTTP 或数据库       |
| `infrastructure/skill`                  | front matter、快照和受限资源读取            | 只读取配置目录，不执行脚本          |
| `infrastructure/tool`                   | Skill 工具与 echo 示例适配                  | 工具必须静态注册                    |
| `application/conversation`              | 会话锁、去重、模型选择和提交编排            | 不依赖 SQL、HTTPX 或 FastAPI        |
| `infrastructure/memory`                 | SQLite 版本迁移、JSON 和短事务仓储          | 不持有模型执行期间的写事务          |
| `infrastructure/provider`               | OpenAI SDK、工具片段与模型事件归一化        | 不选择 Skill 或保存历史             |

包入口与核心契约均有中文说明。没有加入审批、Policy、多 Agent 或数据采集模块。完整前后端链路和断点说明见 [HTTP 运行流程](docs/http-runtime.md)。

配置保留既有 `server/storage/provider/agents/skillsDirectory`；新增可选 `runtime`，见开发示例。模型 Profile 禁止包含 `skillIds`；Skill 使用单独的全局目录。`historyLimit` 仍为消息条数，省略时沿用旧版不限制条数的行为；设置后按完整轮次截取，不转换为轮次数。

Provider 使用官方 `openai` Python SDK 的 `AsyncOpenAI`，通过 `baseUrl + /chat/completions` 访问兼容流式协议。SDK 复用应用显式创建的 HTTPX 连接池；禁用 SDK 自带重试，由适配层统一控制首事件前的重试，避免双重重试。可选 `connectTimeoutSeconds:10`、`readTimeoutSeconds:60`、`maxAttempts:2`（上限 3）；只在当前模型调用尚未输出事件时重试网络/429/5xx。Profile 可配置 `supportsTools:false` 声明不支持工具，Agent 会明确报能力错误，不能借此跳过业务流程；默认 true。不支持 stream_options 的服务可设置 `includeStreamUsage:false`，未知用量保持缺失。配置全来自 JSON；HTTPX 不读取环境代理。

成功请求跨重启重放正文、reasoning 和 usage；相同 ID 不同输入返回冲突。失败同输入最多执行三次（请求级 attempt，与 Provider 单次连接重试不同）；启动将遗留 running 标记为 interrupted。没有接外部写工具，因此有限重试不会重复业务写入。切换模型沿用 sessionId，不创建新会话。

## 验证

根目录 `npm test` 和 `npm run typecheck` 只覆盖 Vue/TypeScript 前端。Python 后端在 `backend` 下执行：

```powershell
uv run --locked ruff check .
uv run --locked python scripts/check_code_style.py
uv run --locked mypy
uv run --locked pytest -q
uv build
```

测试只读取脱敏示例配置，在 pytest 临时目录生成旧版 SQLite，不访问实际 `data/` 或模型。Ruff 负责通用静态规则，mypy 负责严格类型检查；架构测试限制领域层导入和 HTTP 越层依赖，并执行自定义代码规范检查。

代码规范见 [代码规范](docs/code-style.md)：自定义函数最多 4 个业务参数（不含 `self`/`cls`），定义和调用的参数列表单行；被使用的调用结果先赋值给变量；禁止链式方法调用。检查覆盖 `src`、`tests`、`examples`、`scripts`。Ruff formatter 会将长参数列表重新折行，与本项目规范冲突，因此不再作为验收命令；不要对 backend 整库运行 `ruff format`。

API 及 SSE 冻结契约见 [HTTP 契约](docs/http-contract.md)，存储和回退约定见 [存储契约](docs/storage-contract.md)。Skill 格式按 [Agent Skills specification](https://agentskills.io/specification) 解析。可运行确定性演示：

```powershell
uv run --locked python examples/progressive_skill_demo.py
```

该演示只验证“目录 → 激活正文 → 读取一份资源 → 最终回答”，不调用真实大模型或 Dokkan 数据服务。HTTP 和 Provider 测试使用模拟响应与临时 SQLite；真实模型的 Skill 选择质量仍需单独评估。默认启动已切换到 Python，旧 TS `chat` CLI 不再是当前支持入口。
