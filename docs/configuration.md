# 服务端配置

当前服务端为 Python。默认服务根为 `BACKEND_ROOT = repo/backend`，默认读取 `<backend-root>/config/stargazer-agent.json`，即仓库中的 `backend/config/stargazer-agent.json`；也可使用 `--config` 指定其他 JSON 文件。`BACKEND_ROOT` 在此表示路径约定，不是新增环境变量入口；模型、密钥、端口、数据库或 Skill 目录均不读取旧环境变量。

## 创建与选择配置

首次使用在仓库根目录执行以下命令，然后填写 `provider.apiKey`、`provider.baseUrl` 与模型列表：

```powershell
Copy-Item backend/config/stargazer-agent.example.json backend/config/stargazer-agent.json
```

已有 `backend/config/stargazer-agent.json` 时直接编辑，不要用示例覆盖凭据与数据库路径。默认示例为 `backend/config/stargazer-agent.example.json`，使用端口 `3000`、`data/stargazer-agent.sqlite` 和 `examples/skills`，分别解析为后端根下的数据库与 Python 演示 Skill。根 `config/stargazer-agent.example.json` 不再提供。**没有隐式旧配置回退**：缺少新默认配置会报错，不会自动加载仓库根的旧 `config/stargazer-agent.json`。

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
uv run --project backend --locked python -m dokkan_agent.main --config config/local.json
# 显式指定后端根目录
uv run --project backend --locked python -m dokkan_agent.main --backend-root D:\stargazer-agent\backend --config config/local.json
```

从 `backend` 目录运行时，参数同样是 `--config config/local.json`：

```powershell
uv run --locked python -m dokkan_agent.main --config config/local.json
```

路径解析统一遵循以下约定：

| 路径或参数                                | 基准与含义                                                                                     |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 默认后端根                                | 源码运行时为 `repo/backend`，与启动命令的 cwd 无关                                             |
| `--backend-root`                          | 显式指定后端服务根，例如 `D:\stargazer-agent\backend`；独立安装 wheel 时需指定部署中的后端目录 |
| `--project-root`                          | `--backend-root` 的同义兼容参数，语义也是后端根；不能继续传仓库根                              |
| 默认配置                                  | `<backend-root>/config/stargazer-agent.json`                                                   |
| 相对 `--config`                           | 相对于后端根，不相对于 cwd                                                                     |
| `storage.databasePath`、`skillsDirectory` | 相对值均相对于后端根，不相对于 cwd 或配置文件目录；绝对路径直接使用                            |
| Web 静态目录                              | `backend_root.parent / "web" / "dist"`，与配置目录无关                                         |

独立部署应保持 `<deployment>/backend` 与 `<deployment>/web/dist` 同级布局。即使配置文件在其他目录，页面仍从后端根的同级 `web/dist` 提供；移动配置不能改变静态资源定位。

配置不支持热更新，修改后重启 Python 服务。真实配置已被 Git 忽略，不要把密钥提交到示例或浏览器端。

### 已有配置迁移

当前本地配置已迁到 `backend/config/stargazer-agent.json`，其中 `storage.databasePath` 改为 `../data/stargazer-agent.sqlite`，继续引用仓库根下的原数据库；**没有搬动实际 `data/`**。这是保留原库的本地迁移值，不是新默认示例的数据库路径。其他已有配置迁移时也应核对数据库和 Skill 的实际目标：原先的 `backend/examples/skills` 应改为 `examples/skills`，避免重复拼接 `backend`。不要为了匹配新默认值而无意创建空库或移动原库。

## 端口与独立开发配置

- 默认配置沿用 `127.0.0.1:3000`，与 `npm run web:dev` 中 Vite 的 `/api` 代理一致；监听地址由 JSON 决定，不由 `HOST`/`PORT` 环境变量覆盖。
- `backend/config/development.example.json` 使用端口 `3001`、`data/development.sqlite` 和 `examples/skills`，路径值同样没有 `backend/` 前缀；数据库实际位于 `backend/data/development.sqlite`。它适合独立验证：复制为 `backend/config/local.json` 并编辑后，通过上述 `--config config/local.json` 启动；已有 local.json 时不要覆盖。
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
