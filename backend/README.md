# Python Agent 后端

当前完成 T01—T05：工程、配置、内部/外部契约、SQLite 迁移基础、Skill 渐进式披露、Tool 注册和有界 AgentRunner。尚未接入真实 Model Provider、会话仓储和聊天路由；原 TypeScript 后端继续使用。Dokkan 数据服务接入不在当前范围。

## 入口与启动

需要 Python 3.12+ 和 uv。从仓库根目录执行：

```powershell
cd D:\stargazer-agent\backend
uv sync --locked
uv run --locked python -m dokkan_agent.main --config backend/config/development.example.json
```

示例监听 `127.0.0.1:3001`，不会调用示例中的模型或打开数据库。`--config` 的相对路径以**仓库根目录**为基准，而非当前目录；省略时读取现有 `config/stargazer-agent.json`，此时端口也来自该文件。正式本地配置可另存 `backend/config/local.json`（已忽略），不要把真实密钥放入示例。

工程依赖位于 `backend/.venv`，不用仓库旧 `.venv`。开发网络直连 PyPI 曾超时，因此 `pyproject.toml` 显式使用清华 PyPI 镜像，`uv.lock` 记录确切版本、下载来源与哈希；没有以环境变量覆盖应用配置。

源码运行时自动定位仓库根目录；如果独立安装 wheel，需通过 `--project-root D:\stargazer-agent` 显式指定配置和数据的根目录，不能把安装目录或启动目录误当成项目目录。

调试器选择 `backend/.venv/Scripts/python.exe`，启动模块为 `dokkan_agent.main`，参数与上面相同。可依次断点：

1. `src/dokkan_agent/main.py::main`：进程入口，解析配置路径并启动 Uvicorn。
2. `src/dokkan_agent/bootstrap/application.py::create_app`：组合根，读取配置并创建应用。
3. `src/dokkan_agent/interfaces/http/app.py::create_http_app`：注册 HTTP 路由与生命周期。

当前 `GET /health/live` 返回 `200 {"alive":true}`；`GET /health/ready` 返回 `503` 和 `ready:false`，因为真实 Provider、会话存储和聊天路由尚未接入。`/api/*` 只有 DTO 和文档，尚未注册。不要把 Vue 代理切到 Python，聊天功能在 T08 接入。

## 职责与依赖

| 目录 | 职责 | 依赖边界 |
| --- | --- | --- |
| `bootstrap` | 文件配置、路径基准、应用装配 | 组合根可以依赖各层 |
| `interfaces/http` | HTTP DTO、SSE 编码、路由 | 不直连 SQLite/Provider |
| `domain/agent` | 模型消息、流事件、ModelGateway | 仅标准库和其他领域契约 |
| `domain/conversation` | 请求身份、完整轮次、请求状态 | 不含 HTTP 或锁实现 |
| `domain/skill` | L1 描述、L2 激活、L3 单资源契约 | 不访问磁盘，不绑定模型 |
| `domain/tool` | 完整调用、注册定义、成功/失败结果 | 不执行文件或脚本 |
| `application/runtime` | ContextBuilder、AgentRunner、预算和事件聚合 | 每条消息独立 RunContext，不负责落库 |
| `application/skill`、`application/tool` | Skill/Tool 用例编排和注册 | 不直接访问文件、HTTP 或数据库 |
| `infrastructure/skill` | front matter、快照和受限资源读取 | 只读取配置目录，不执行脚本 |
| `infrastructure/tool` | Skill 工具与 echo 示例适配 | 工具必须静态注册 |
| `infrastructure/memory` | SQLite 版本化迁移 | 当前只显式操作指定测试库 |

ConversationService、Provider 和 HTTP 业务路由仍留给 T06—T08。包入口与核心契约均有中文说明。没有加入审批、Policy、多 Agent 或数据采集模块。

配置保留既有 `server/storage/provider/agents/skillsDirectory`；新增可选 `runtime`，见开发示例。模型 Profile 禁止包含 `skillIds`；Skill 使用单独的全局目录。`historyLimit` 仍为消息条数，省略时沿用旧版不限制条数的行为；设置后按完整轮次截取，不转换为轮次数。

## 验证

在 `backend` 下执行：

```powershell
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -q
uv build
```

测试只读取脱敏示例配置，在 pytest 临时目录生成旧版 SQLite，不访问实际 `data/` 或模型。Ruff 负责格式与静态规则，mypy 负责严格类型检查；架构测试限制领域层导入和 HTTP 越层依赖。

API 及 SSE 冻结契约见 [HTTP 契约](docs/http-contract.md)，存储和回退约定见 [存储契约](docs/storage-contract.md)。Skill 格式按 [Agent Skills specification](https://agentskills.io/specification) 解析。可运行确定性演示：

```powershell
uv run --locked python examples/progressive_skill_demo.py
```

该演示只验证“目录 → 激活正文 → 读取一份资源 → 最终回答”，不调用真实大模型或 Dokkan 数据服务。下一批是 T06—T08 的会话仓储、Provider 和 Web 路由。
