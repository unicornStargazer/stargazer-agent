# Tool 扩展

Tool 是由 Python 服务端明确注册给模型的一项能力。Skill Catalog 只能提示何时使用工具，不能注册工具或自行获得文件、网络、命令等权限。

## 当前默认工具

正式注册集合在 `backend/src/dokkan_agent/bootstrap/runtime.py::create_agent_runner` 装配，通过 `infrastructure/tool/skill_tools.py` 创建：

- `activate_skill`：激活已发现 Skill 的正文与资源清单。
- `read_skill_resource`：读取已激活 Skill 中受限的单份文本资源。

工具只访问配置指定的 Skill 目录，不提供任意文件读取、Shell、脚本执行或 Dokkan 数据查询。`allowed-tools` 元数据不授予权限。

```text
用户消息 -> AgentRunner -> 模型请求工具 -> ToolRegistry 校验与预算 -> 已注册处理器 -> 模型继续生成
```

## 示例与扩展入口

无副作用的 `echo_text` 示例位于 `backend/src/dokkan_agent/infrastructure/tool/echo_tool.py`，**正式 factory 默认不注册**，仅在演示/测试中显式装配。它接受长度 1—4000 的 `text`，不访问网络、文件或数据库。

新增业务 Tool 时：

1. 使用 `application/tool/function_tool.py` 的 `ToolParameters` 定义严格参数，禁止额外字段和自动类型转换。
2. 用 Pydantic 定义输出，以 async handler 调用应用用例；不要把 HTTP 请求、凭据或未校验的路径直接交给处理器。
3. 用 `FunctionTool` 包装，并在 Python 组合根显式加入 `application/tool/registry.py::ToolRegistry`。
4. 测试输入校验、输出格式、预算、取消与错误边界。接入有外部写副作用的工具前，还需单独设计副作用幂等，不能只依赖聊天请求去重。

工具调用必须等当前模型流正常完成并收齐参数后才执行。注册器拒绝未知名称、重复 JSON 键、非有限数值与无效参数，处理器异常会转换为脱敏错误；预算耗尽终止整轮，不允许无限工具修正循环。旧 TS 的 `src/tools/default-tool-registry.ts` 与 `AgentTool` 不再是当前扩展入口。

详细执行顺序与限制见 [Agent 内核](../backend/docs/runtime-core.md#工具定义和扩展)，HTTP 与持久化边界见 [运行流程](../backend/docs/http-runtime.md)。
