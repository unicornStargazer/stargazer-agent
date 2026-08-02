# 服务端配置

服务仅从 `config/stargazer-agent.json` 读取配置，不再读取模型、密钥、端口或数据库路径相关的环境变量。

首次使用时，将 `config/stargazer-agent.example.json` 复制为 `config/stargazer-agent.json`，填写 `provider.apiKey`。实际配置文件已被 Git 忽略，避免提交凭据。

```json
{
  "server": { "host": "127.0.0.1", "port": 3000 },
  "storage": { "databasePath": "data/stargazer-agent.sqlite" },
  "provider": {
    "apiKey": "你的 API Key",
    "baseUrl": "https://api.openai.com/v1",
    "includeStreamUsage": true
  },
  "agents": {
    "defaultProfileId": "fast",
    "profiles": [
      {
        "id": "fast",
        "name": "快速回答",
        "model": "gpt-4.1-mini",
        "historyLimit": 12
      }
    ]
  }
}
```

`agents.profiles` 至少包含一项，且 `defaultProfileId` 必须引用其中一个 `id`。每个 Profile 可选 `systemPrompt` 与 `historyLimit`；前者定义该模型的系统提示，后者定义发送给模型的历史消息窗口。

`skillsDirectory` 是可选字段。指定后，目录下的 `SKILL.md` 会作为全局业务 Skill Catalog 加载，而不会生成额外 Profile 或出现在模型选择菜单。所有 Profile 共享已加载的 Skill；模型和历史窗口仍分别由该 Profile 的 `model`、`historyLimit` 决定。详见 [业务 Skill](skills.md)。
