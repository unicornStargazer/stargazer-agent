# 业务 Skill

当前 Python 后端的 Skill 是可复用业务指令与受限资源目录，不决定模型、历史窗口或 Provider，也不能自行注册 Tool。模型由服务端 JSON 的 `agents.profiles` 决定，所有 Profile 共享 `skillsDirectory` 指定的全局 Catalog。

## Python Skill 格式

在 `skillsDirectory` 下创建与 Skill name 同名的子目录及 `SKILL.md`：

```text
my-skills/
  order-support/
    SKILL.md
    references/
      response-checklist.md
```

```md
---
name: order-support
description: 帮助整理用户提供的订单信息，并在缺少订单号时提出澄清问题。
---

Ask for an order number when it is required.
Never invent an order status or claim access to an unregistered order service.
```

`name` 和 `description` 必填。名称须与目录一致，长度 1—64，使用小写 Unicode 字母、数字和连字符，不允许首尾或连续连字符；不能沿用旧版大写展示名或下划线规则。描述最多 1024 字符。还支持 `license`、`compatibility`、字符串键值 `metadata` 和 `allowed-tools`；未知顶层字段拒绝加载，`model`、`historyLimit` 属于 Profile，不能写入 Skill。

`allowed-tools` 只是兼容性提示，不授权工具或执行脚本。完整字段、安全限制与资源格式见 [Agent 内核](../backend/docs/runtime-core.md#skill-文件支持范围)。

## 配置与启用

Python 默认配置为 `backend/config/stargazer-agent.json`，也可用 `--config config/local.json` 指定后端根下的其他文件；缺少新配置会报错，不隐式回退到旧根配置。以下是配置片段，需合并到包含 `server/storage/provider/agents` 的完整 JSON 中：

```json
{
  "skillsDirectory": "examples/skills"
}
```

该路径以**后端根目录**为基准，默认 `BACKEND_ROOT = repo/backend`，不随 cwd 或配置文件所在目录变化。因此 `examples/skills` 指向 `backend/examples/skills`，其中提供明确标记的 `material-analysis-demo`，不连接游戏事实查询服务。`--backend-root` 可覆盖后端根；旧 `--project-root` 是同义兼容参数，含义也为后端根。自建目录时，将值换成自己的兼容目录；不需要 Skill 时省略 `skillsDirectory`。

**根 `examples/skills` 仍是旧 TS 格式**，不能直接给 Python 加载；它与后端根下的 `examples/skills` 不是同一目录。默认和开发示例均使用后者，不再引用根旧目录；根旧配置示例不再提供。

配置与目录修改后重启 Python 服务；格式无效会使启动失败。运行中部署文件改变会返回 `SKILL_CHANGED`，需检查并重启以重新发现快照。

## 渐进式披露

1. **L1**：每条用户消息的首次模型请求只提供各 Skill 的 `name/description` 摘要，不注入全部正文。
2. **L2**：模型通过已注册的 `activate_skill(name)` 激活正文、版本与资源清单；用户也可在当前消息明确写 `$order-support`。
3. **L3**：通过 `read_skill_resource(name, relative_path)` 读取已激活 Skill 的单份 UTF-8 文本资源。

每条消息创建新的 RunContext，旧工具结果与 Skill 正文不常驻，历史消息中的 `$skill-name` 不会触发新一轮激活。Catalog 为版本快照会在磁盘发现时读取文件与计算哈希；“按需加载”是指正文按需进入模型上下文，而不是启动时完全不读文件。

资源仅来自 Skill 内的 `references/`、`assets/`、`scripts/`；脚本和二进制只公开名称、版本和类型，不执行。路径越界、外链与文件变化受检查；开发辅助 Skill 目录不会自动成为产品业务目录。工具、资源与披露均受运行预算限制，详见 [Tool 扩展](tools.md) 和 [Agent 内核](../backend/docs/runtime-core.md)。
