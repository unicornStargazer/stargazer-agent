# SQLite 迁移与会话提交契约

T02 提供版本化 DDL 和显式 `migrate_database(path)`，使用临时测试库完成验证。启动生命周期暂不调用迁移，也没有指向实际 `data/` 的迁移命令。T06 才实现完整仓储、锁、请求重放与恢复，不能把 DDL 验证称为这些功能已经完成。

## 旧数据兼容

保留 `conversation_sessions` 和 `conversation_messages` 表名、联合主键、sequence 和 UTC epoch 毫秒时间语义。不重排旧序号，不重新裁剪正文，不改写已有 `reasoning/usage_json`。旧版没有 `profile_id/reasoning/usage_json` 时只添加可空列；既有缺失元数据保持 NULL。

每个 SQLite 连接必须开启 `PRAGMA foreign_keys=ON`。迁移使用 `BEGIN IMMEDIATE` 和短事务，迁移脚本逐条执行，避免 `executescript` 的隐式提交。全部待执行 DDL、补列、版本记录和外键检查在同一个事务；失败回滚，取消向上传播，连接关闭。SQLite 可能创建空文件，但失败不应留下半迁移的表结构或版本记录。

`agent_schema_migrations(version, applied_at_ms)` 记录版本。现有记录必须为已知版本的连续前缀；未知、更高、缺失中间版本时拒绝修改。重复调用返回空版本集合；不再次增列，不更新既有记录时间。

| 版本 | 文件 | 内容 |
| --- | --- | --- |
| 1 | `001_conversations.sql` | 建立现有会话结构；由迁移器补齐老表缺少的可空列 |
| 2 | `002_agent_requests.sql` | 新请求表、状态约束及 running 部分索引 |

测试用代码生成两种脱敏旧库，不提交二进制库：缺少元数据的旧结构、包含 reasoning/usage/Profile 的当前结构。还验证新库、重复执行、不兼容结构回滚、未来版本拒绝、请求约束及会话级联删除。

## 新请求表

| 字段 | 语义与约束 |
| --- | --- |
| `session_id/request_id` | 联合主键；session FK 删除级联 |
| `request_fingerprint` | `v1:` + SHA-256，输入为规范化 message 与显式 profileId，含规范版本 |
| `status` | running / succeeded / failed / interrupted |
| `attempt` | 从 1 开始的执行次数；失败重试递增 |
| `profile_id` | 此次实际采用的模型，不等于指纹中的可选显式选择 |
| `response_json` | 成功后保存 `{"message":...}` 完整重放结果；只有 succeeded 可非 NULL |
| `error_code` | 脱敏错误类别，成功为 NULL；不保存原始异常响应 |
| `created_at_ms/updated_at_ms` | UTC epoch 毫秒；重试保留创建时间 |

指纹算法在 `ConversationCommand.fingerprint()`；JSON 使用排序键、紧凑分隔符、ASCII 转义、UTF-8 编码，并包含 `version:1`。会话 ID 和请求 ID 已是联合键，不重复放入指纹。显式 profileId 与省略不同，保证同键不同选择不会误重放。

## 后续仓储必须遵守的事务语义

1. 同一会话串行，不同会话并发；当前单进程单 worker，不宣称跨进程锁。
2. 先在短事务创建/更新 running 记录，模型/工具执行在事务外。
3. 成功时在同一短事务追加用户和助手消息、更新会话 Profile、写入 succeeded 和完整响应；提交成功后发 SSE done。
4. 模型或存储失败不能追加半轮历史；失败请求标为 failed。现阶段工具无外部写副作用，同输入允许有限重试，attempt 递增。
5. 成功同键同指纹直接重放正文和元数据；不同指纹冲突。运行中同输入等待原任务完成，不重复执行模型。
6. 重启后遗留 running 标为 interrupted；不猜测远端是否完成，不自动续跑。取消释放锁和连接。
7. 删除会话级联清理消息和请求，运行中拒绝删除。

`historyLimit` 限制消息条数；构造上下文时只取预算内的完整轮次，不能把 12 条解释成 12 轮或保留半轮。未来如果接入写工具，须另行设计工具副作用幂等，不能只靠会话请求去重。

## 切换与回退边界

本阶段原 TypeScript、原配置、实际数据库均保持现有运行方式。正式切换前必须停写，使用 SQLite 备份能力创建一致副本，先在副本升级和验收；WAL 活跃时不能只复制主文件。禁止 TS/Python 并行写同一个实际库。

当前增量仅添加可空列和独立表，理论上旧 TS 能继续读取原表；T10 仍须用旧客户端实际验证。验证通过可保留新消息后回退；否则使用切换前备份，先导出切换后增量，明确恢复备份会舍弃哪些写入。没有自动降级 DDL，不执行 DROP TABLE 或删除真实数据。
