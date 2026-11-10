# 业务 Skill

Skill 是可复用的业务指令片段，只回答“这个 Agent 应如何处理某类业务”。它不决定模型、历史窗口、Provider，也不能自行获得 Tool 权限。

模型由 `config/stargazer-agent.json` 中 `agents.profiles[].model` 决定；Tool 由服务端代码中的 `ToolRegistry` 显式注册。Skill 目录是全局能力目录，所有 Profile 与模型共享其中已加载的 Skill。

## 新增 Skill

在 `skillsDirectory` 对应目录下创建一个以 Skill ID 命名的子目录和 `SKILL.md`：

```text
examples/skills/
  order-support/
    SKILL.md
```

目录名是 Skill ID，只能使用英文字母、数字、`-`、`_`。`SKILL.md` 格式如下：

```md
---
name: Order Support
---

You are an order support assistant.
Ask for an order number when it is required.
Never invent an order status.
```

front matter 目前只允许 `name`。`model` 和 `historyLimit` 会在启动时被拒绝，因为它们属于 Agent Profile 配置。

## 启用 Skill 目录

在 `config/stargazer-agent.json` 配置全局 Skill 根目录：

```json
{
  "skillsDirectory": "examples/skills",
  "agents": {
    "defaultProfileId": "support",
    "profiles": [
      {
        "id": "support",
        "name": "订单支持",
        "model": "gpt-4.1-mini",
        "historyLimit": 12
      }
    ]
  }
}
```

重启服务后生效。目录中每个合法的 `SKILL.md` 都会加入全局 Skill Catalog，并注入每个 Profile 的系统提示。Skill 目录名重复或文档格式无效会使启动失败，避免配置静默失效。
