# 服务端配置

当前服务端为 Python。默认读取仓库根目录的 `config/stargazer-agent.json`；也可使用 `--config` 指定其他 JSON 文件。不读取模型、密钥、端口、数据库或 Skill 目录相关的旧环境变量。

## 创建与选择配置

已有 `config/stargazer-agent.json` 时，直接编辑所需字段，不要用示例覆盖凭据与数据库路径。首次使用可参考 `config/stargazer-agent.example.json` 的服务端字段，填写 `provider.apiKey`、`provider.baseUrl` 与模型列表。**根示例中的 `skillsDirectory: "examples/skills"` 指向旧 TS 格式，Python 不能直接加载**；请先省略该字段，或改为 `backend/examples/skills` 使用演示 Skill。

以下为可供填写的最小配置，不包含真实密钥：

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

在仓库根目录执行：

```powershell
# 默认配置，与 npm start / npm run dev / npm run start:server 相同
uv run --project backend --locked python -m dokkan_agent.main
# 指定独立配置
uv run --project backend --locked python -m dokkan_agent.main --config backend/config/local.json
```

`--config` 相对路径、`storage.databasePath` 和 `skillsDirectory` 都以**仓库根目录**为基准，即使从 `backend` 启动也是如此。源码运行时自动定位根目录；独立安装 wheel 时使用 `--project-root` 显式指定。配置不支持热更新，修改后重启 Python 服务。真实配置已被 Git 忽略，不要把密钥提交到示例或浏览器端。

## 端口与独立开发配置

- 默认配置沿用 `127.0.0.1:3000`，与 `npm run web:dev` 中 Vite 的 `/api` 代理一致；监听地址由 JSON 决定，不由 `HOST`/`PORT` 环境变量覆盖。
- `backend/config/development.example.json` 使用 `3001`、`backend/data/development.sqlite` 和演示 Skill，适合独立验证。复制为 `backend/config/local.json` 并编辑后，通过上述 `--config` 启动；已有 local.json 时不要覆盖。
- 使用 3001 示例时，先 `npm run build:web`，再访问 `http://127.0.0.1:3001` 的同源页面。现有 Vite 代理仍是 3000，不会随 `--config` 自动变化。

启动会创建并迁移所选数据库；升级旧库前先停写并做一致备份，开发验证优先使用独立库。启动本身不发送付费模型请求，健康检查也不探测远程模型。详见 [后端启动](../backend/README.md) 与 [存储契约](../backend/docs/storage-contract.md)。

## 模型与 Provider

`agents.profiles` 至少包含一项，ID 不重复，`defaultProfileId` 必须引用其中一个 `id`。每项需提供 `id/name/model`，可选：

- `systemPrompt`：该模型的基础系统提示；省略表示不额外配置，不可填 null。
- `historyLimit`：历史**消息条数**，不是轮次数；按最近的完整轮次截取，例如 12 条最多 6 轮。省略不限制条数，但仍受运行上下文预算约束，不可填 null。
- `supportsTools`：默认 true；不支持工具的模型可显式设为 false，运行时会返回能力错误，不会悄悄跳过工具流程。

Profile 不支持 `skillIds`；所有模型共享全局 Skill Catalog。模型切换保留会话，见 [模型切换](model-switching.md)。

`provider.includeStreamUsage` 为必填布尔值；上游不支持 `stream_options` 时设为 false，未知用量不伪造为零。可选 `connectTimeoutSeconds`（默认 10，范围 1—120）、`readTimeoutSeconds`（默认 60，范围 1—600）、`maxAttempts`（默认 2，范围 1—3）。只在当前模型调用尚未输出事件时重试网络/429/5xx。HTTPX 不读取环境代理。

## Skill 与运行预算

`skillsDirectory` 可省略；指定后加载全局目录，而不会生成额外 Profile 或出现在模型菜单。Python Skill 要求 `name` 和 `description`，使用按需披露，不把全部正文注入每次请求；详见 [业务 Skill](skills.md)。

可选 `runtime` 配置每条消息的独立预算，省略时使用以下默认值：

```json
{
  "runtime": {
    "maxModelCalls": 12,
    "maxToolExecutions": 24,
    "maxActivatedSkills": 4,
    "maxResourceReads": 8,
    "maxResourceCharacters": 16000,
    "maxDisclosureCharacters": 64000,
    "maxContextCharacters": 128000
  }
}
```

这些值必须是正整数。字符预算不是精确 Token 计数；含义与失败边界见 [Agent 内核运行流程](../backend/docs/runtime-core.md)。Python 配置拒绝未知字段，不要沿用旧 Skill/Profile 字段或误以为旧环境变量仍然生效。
