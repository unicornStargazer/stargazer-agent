# 模型切换

模型列表只由服务端配置文件 `config/stargazer-agent.json` 中的 `agents.profiles` 决定。页面启动后通过 `GET /api/profiles` 获取安全摘要，只能选择已配置的模型，不能提交 API Key、Base URL 或任意模型名。

示例配置默认提供 `gpt-4.1-mini` 和 `o3` 两个模型。复制 `config/stargazer-agent.example.json` 为 `config/stargazer-agent.json`，填入 `provider.apiKey` 后重启服务。

```json
{
  "agents": {
    "defaultProfileId": "fast",
    "profiles": [
      { "id": "fast", "name": "快速回答", "model": "gpt-4.1-mini" },
      { "id": "reasoning", "name": "深度分析", "model": "o3" }
    ]
  }
}
```

选择模型后的行为：

- 当前会话保持不变，不会自动新建会话；
- 已有消息作为完整上下文传给新模型，后续回复继续写入当前会话；
- 服务端将会话当前 `profileId` 更新为所选模型，但不会删除、改写或迁移已保存消息；
- 若两个模型配置了不同的 `systemPrompt`，新提示仅对切换后的调用生效。

模型列表不支持热更新，修改配置文件后需要重启 Node 服务。
