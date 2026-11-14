# 模型切换

模型列表只由 Python 服务端加载的 JSON 配置中的 `agents.profiles` 决定，默认文件为 `backend/config/stargazer-agent.json`，也可通过 `--config config/local.json` 指定；相对路径以默认的 `repo/backend` 后端根为基准，与 cwd 无关。缺少新配置会报错，不隐式回退到根旧配置。页面启动后通过 `GET /api/profiles` 获取安全摘要，只能选择已配置的模型，不能提交 API Key、Base URL 或任意模型名。

以下片段以 `gpt-4.1-mini` 和 `o3` 演示多模型配置，实际可用模型由你的兼容服务决定，不代表默认示例承诺提供这些模型。已有配置时直接编辑，不要覆盖凭据。首次创建配置请按 [服务端配置](configuration.md) 从 `backend/config/stargazer-agent.example.json` 复制并填写 `provider.apiKey`、`provider.baseUrl` 与模型列表；其中 `skillsDirectory: "examples/skills"` 相对于后端根，指向 Python 演示 Skill。以下仅为 `agents` 片段，不是完整启动配置。

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
- 已有历史按所选 Profile 的 `historyLimit` 和运行预算选取最近的完整轮次后传给新模型，后续回复继续写入当前会话；
- 成功提交回复时，服务端将会话当前 `profileId` 更新为所选模型，但不会删除、改写或迁移已保存消息；
- 若两个模型配置了不同的 `systemPrompt`，新提示仅对切换后的调用生效。

模型列表不支持热更新，修改配置文件后需要重启 Python 服务。所有 Profile 共享全局 Skill Catalog，Profile 不支持 `skillIds`；工具能力要求见 [后端 README](../backend/README.md)。
