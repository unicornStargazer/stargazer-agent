# Web 协议迁移契约

协议沿用旧 TypeScript 后端与 Vue 客户端约定，当前由 `backend/src/dokkan_agent/interfaces/http/` 实现，与 `web/src/services/chat-api.ts` 对接。旧根 `src/http/`、`src/chat/` 仅为迁移来源，不再是当前代码入口；默认 npm 后端入口已启动 Python，启动方式见 [后端 README](../README.md)。

## 请求与路由

| 方法/路径               | 输入             | 成功输出                                                                           |
| ----------------------- | ---------------- | ---------------------------------------------------------------------------------- |
| `GET /api/status`       | 无               | `ready`、`model`、`conversationStorage`、可选 `defaultProfile`                     |
| `GET /api/profiles`     | 无               | `{"profiles":[{"id":"default","name":"默认模型","model":"configure-your-model"}]}` |
| `GET /api/history`      | 查询 `sessionId` | `{"messages":[用户/助手消息]}`；空会话 `[]`                                        |
| `DELETE /api/history`   | 查询 `sessionId` | `{"deleted":true}`；运行中拒绝                                                     |
| `POST /api/chat`        | 下述 JSON        | `{"message":助手消息}`                                                             |
| `POST /api/chat/stream` | 同上             | 下述 SSE                                                                           |

```json
{
  "sessionId": "session_1",
  "requestId": "request_1",
  "message": "请分析我提供的卡片资料",
  "profileId": "default"
}
```

`sessionId/requestId/profileId` 裁剪 JavaScript 空白后，只接受 ASCII 字母、数字、下划线、连字符，长度 1—128。`profileId` 可省略，但不可传 null/空字符串；省略使用当前会话选择或默认值，不能自动新建会话。正文同样裁剪 JavaScript 空白，不能为空，限制 **16000 UTF-16 单元**，例如 8000 个普通 emoji 可接受，8001 个拒绝。额外输入字段继续忽略；已有字段不做字符串/数字/布尔自动转换。

JSON 总请求体沿用 **32 KiB** 上限，与字符上限是独立约束，中文/emoji 可能先触及字节上限。媒体类型、流式读取体积和字段错误已统一映射，不使用 FastAPI 默认 422 错误响应。所有外部输入在进入应用层前转成 `ConversationCommand`。

助手消息示例：

```json
{
  "role": "assistant",
  "content": "基于你提供的材料……",
  "reasoning": "Provider 公开的推理摘要",
  "usage": { "inputTokens": 3, "outputTokens": 6, "totalTokens": 9 }
}
```

用户只有 `role:user`、`content`。长期历史不保存 system/tool 消息。未知 reasoning/usage 字段省略，不能填 null 或伪造零；usage 的已知计数是非负安全整数。`reasoningTokens` 为可选子项，不额外加进总计。旧记录无元数据时仍正常显示。

序列化所有响应使用 `by_alias=True, exclude_none=True`。Profile 对外仅公开 `id/name/model`，不得公开密钥、baseUrl、系统提示或 Skill 绑定。`conversationStorage` 为 `sqlite` 或 `memory`，Python 完整实现选用前者。

## 流事件

响应头为 `Content-Type: text/event-stream; charset=utf-8`、`Cache-Control: no-store`。每帧由 `event` 和单行 JSON `data` 组成，以空行结束。编码器转义正文换行，不能把工具/用户文本直接拼成协议行。

| event       | data                                                                    | 语义                                         |
| ----------- | ----------------------------------------------------------------------- | -------------------------------------------- |
| `chunk`     | `{"content":"增量正文"}`                                                | 可见文字；对应内部 ContentDelta              |
| `reasoning` | `{"content":"公开推理增量"}`                                            | Provider 已公开的内容，不索取隐藏思维链      |
| `usage`     | `{"usage":{"inputTokens":3,"totalTokens":9}}`                           | 本轮当前汇总用量，不是待前端自行相加的增量   |
| `done`      | `{}`                                                                    | **完整轮次和成功请求结果事务提交后**发送一次 |
| `error`     | `{"code":"MODEL_UNAVAILABLE","message":"模型暂时不可用，请稍后重试。"}` | 失败后关闭，不能再发 done                    |

确定性样例见 [success.sse](examples/success.sse)，由契约测试与编码结果逐字比较。流开始前错误使用普通 HTTP 错误；响应头已发送后使用 SSE error。客户端断开应取消上游生成，不能继续无限执行。模型单次 `ModelCompleted` 不等于整个 Agent 完成。

同一次模型调用的 usage 可能多次累计上报，取最后有效统计；多次模型调用再求和。成功结果保留所有已发 chunk，不能只持久化最后一次模型调用文字。幂等重放包含正文、reasoning 和 usage，最后 done；无需伪装成原始分片时间线。

## 错误契约

HTTP 格式为 `{"error":{"code":"...","message":"..."}}`。不回传堆栈、原始上游 JSON、数据库内容或配置错误输入。已有错误保持含义，新增错误区分执行内核失败。

| HTTP | code                             | 说明                                       |
| ---- | -------------------------------- | ------------------------------------------ |
| 400  | INVALID_REQUEST                  | JSON、标识、正文等校验失败                 |
| 413  | REQUEST_TOO_LARGE                | 请求体超过字节上限                         |
| 415  | UNSUPPORTED_MEDIA_TYPE           | Content-Type 必须为 application/json       |
| 409  | REQUEST_CONFLICT                 | requestId 已用于其他消息或不同显式 Profile |
| 409  | SESSION_BUSY                     | 会话正在生成回复，暂时无法删除             |
| 400  | UNKNOWN_PROFILE                  | 请求的 Agent Profile 不存在                |
| 503  | CONVERSATION_STORAGE_UNAVAILABLE | 会话存储暂时不可用                         |
| 502  | MODEL_UNAVAILABLE                | 模型上游失败                               |
| 501  | STREAMING_UNAVAILABLE            | 保留旧服务未启用流式时的语义               |
| 502  | MODEL_CAPABILITY_UNSUPPORTED     | 模型不支持此次所需能力，不能悄悄跳过工具   |
| 422  | AGENT_BUDGET_EXCEEDED            | 有界运行预算耗尽，未提交成功轮次           |
| 503  | SKILL_UNAVAILABLE                | 部署文件改变或不可用，需检查/重启          |
| 500  | INTERNAL_ERROR                   | 未预期的服务内部错误，不伪装成模型不可用   |

工具级可恢复失败使用独立 `ToolErrorCode` 返回模型；最终 HTTP 错误只在运行不能继续时发出。异常映射在 `interfaces/http/error_mapper.py`；同一请求超过三次运行尝试返回 409 REQUEST_CONFLICT，提示重新发送。
