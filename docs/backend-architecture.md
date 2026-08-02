# 后端架构

后端按职责分层，而不是按 Fastify、SQLite 或 OpenAI 的技术细节组织。这样新增模型供应商、存储实现或业务 Skill 时，核心对话流程不需要修改。

```text
HTTP Controller                 Application Service              Domain / Ports                 Infrastructure
------------------------------  -------------------------------  -----------------------------  -----------------------------
http/api-routes.ts              application/conversation-service  profiles/profile-agent.ts      memory/sqlite-conversation-store.ts
  POST /api/chat                  requestId 幂等                    Profile 选择与会话绑定          SQLite 会话仓储
  POST /api/chat/stream           同会话串行                        chat/agent.ts                  providers/openai-compatible.ts
  GET/DELETE /api/history         请求缓存与清理                    对话轮次、Tool 编排              OpenAI 兼容模型适配器
        |                                   |                              |                              |
        +----------------------------------->+------------------------------>+------------------------------>+
```

## 包职责

| 目录              | 类比 Java 后端              | 负责内容                                               | 不负责内容                              |
| ----------------- | --------------------------- | ------------------------------------------------------ | --------------------------------------- |
| `src/http`        | Controller / Web Adapter    | 路由、入参校验、SSE、HTTP 错误映射、静态资源           | 会话编排、直接操作 SQLite、调用模型 API |
| `src/application` | Application Service         | 幂等、同会话串行、用例级调用顺序                       | Fastify 协议、模型供应商协议            |
| `src/chat`        | Domain Service + Port       | 对话上下文、轮次持久化、受控 Tool 调用、模型和仓储契约 | Fastify、SQLite、OpenAI SDK             |
| `src/profiles`    | Domain Orchestrator         | 选择和绑定 Profile、缓存对应 Agent                     | HTTP、SQL、模型协议                     |
| `src/memory`      | Repository / Infrastructure | SQLite 表、事务、单连接队列、会话读写                  | 对话策略和 Profile 决策                 |
| `src/providers`   | Client / Provider Adapter   | OpenAI 兼容请求、超时、JSON 和 SSE 协议解析            | 会话历史和持久化                        |
| `src/bootstrap`   | Composition Root            | 环境变量解析、SQLite/Provider/Fastify 的具体装配       | 业务规则                                |
| `src/server.ts`   | Main Class                  | 启动进程、监听端口、输出启动结果                       | 创建和编排全部依赖                      |

## 请求路径

普通请求和流式请求都先进入 `ConversationService`。该服务按 `sessionId + requestId` 去重，并保证同一会话内的模型调用串行执行。

随后 `ProfileAgent` 解析请求 Profile：首轮会绑定到 SQLite，后续请求不能切换 Profile。它取得对应的 `ChatAgent`，由后者组合系统提示、历史消息和当前用户消息。模型能力经 `ChatModel` Port 调用，因此 `ChatAgent` 不需要知道实际是 OpenAI 兼容接口还是测试替身。

流式链路中，`OpenAICompatibleChatModel` 把供应商 SSE 转成 `ModelStreamEvent`。HTTP 层再转换为浏览器 SSE：`chunk`（正文）、`reasoning`（公开推理）和 `usage`（Token 用量）。会话只在模型流正常完成后写入用户消息和最终回复。

## 启动装配

`src/server.ts` 调用 `createServerApplication()`。组合根按以下顺序创建依赖：

1. `runtime-configuration.ts` 读取并校验环境变量。
2. 打开 `SqliteConversationStore`，并加载环境 Profile 与 `SKILL.md` Profile。
3. 创建 OpenAI 兼容模型工厂，供 `ProfileAgent` 按 Profile 使用。
4. 创建默认 `ChatAgent`，用于历史查询与没有 Profile 的兼容场景。
5. 将 Agent 适配为 `ConversationService`，并注册到 Fastify。

新增功能时遵守依赖方向：`http -> application -> chat/profiles`；`memory` 和 `providers` 实现 `chat` 定义的契约；`bootstrap` 是唯一选择具体实现的地方。
