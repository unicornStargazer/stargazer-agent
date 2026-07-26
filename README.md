# Stargazer Agent

Stargazer Agent 是一个可快速运行的 TypeScript 文本对话 Agent，提供浏览器工作台和 CLI 两种入口。Web 服务使用 SQLite 保存会话历史，并通过 OpenAI 兼容的 `/chat/completions` 接口调用模型。

当前实现了连续文本对话、Profile 化系统提示、SQLite 会话记忆、流式文本输出，以及受控 Tool 调用的核心编排。默认不注册任何 Tool；不会开放文件系统、命令执行或网络访问等高风险能力。Policy、审批、长期记忆、多 Agent 和复杂运行时仍不在当前范围内。

## 环境

- Node.js 20.19+，推荐 Node.js 22 LTS；Node.js 21 使用构建兼容层。
- npm

## 安装与开发

```powershell
npm install
npm run format:check
npm run lint
npm run typecheck
npm test
```

## 配置

密钥只从环境变量读取，不要把它写入源码或提交到仓库。

```powershell
$env:OPENAI_API_KEY = "你的密钥"
$env:OPENAI_MODEL = "gpt-4.1-mini"
# 可选，默认 https://api.openai.com/v1
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
# 可选，为所有 Web 会话设置统一系统提示
$env:STARGAZER_SYSTEM_PROMPT = "回答要简洁"
# 可选，默认 ./data/stargazer-agent.sqlite
$env:STARGAZER_DATABASE_PATH = "D:\\agent-data\\stargazer-agent.sqlite"
# 可选，与 STARGAZER_DATABASE_PATH 二选一，默认 ./data
$env:STARGAZER_DATA_DIR = "D:\\agent-data"
# 可选：受控的 Agent Profile 列表。浏览器只会看到 id、名称和模型名。
# API Key 与 Base URL 仍只从上面的服务端环境变量读取。
$env:STARGAZER_AGENT_PROFILES = '[{"id":"concise","name":"简洁助手","model":"gpt-4.1-mini","systemPrompt":"回答要简洁","historyLimit":12},{"id":"detailed","name":"详细助手","model":"gpt-4.1-mini","systemPrompt":"给出必要的推理和示例","historyLimit":24}]'
```

## Web 工作台

开发时同时启动 Node API 和 Vite 开发服务器：

```powershell
npm run web:dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 会把 `/api` 请求代理到 `http://127.0.0.1:3000`，修改 Vue 组件后可立即热更新。

需要用单端口验证生产构建时运行：

```powershell
npm run web
```

该命令先生成 `web/dist`，再启动同源 Web 服务。浏览器访问 `http://127.0.0.1:3000`；可通过 `HOST` 和 `PORT` 环境变量修改监听地址和端口。

页面提供多会话导航、安全 Markdown 与代码块展示、复制、失败重试和移动端布局。浏览器保存会话列表和页面消息，模型上下文由服务端 SQLite 保存；删除会话时会同时清除两侧记录。

Profile 由服务端环境变量 `STARGAZER_AGENT_PROFILES` 管理。未设置时自动使用与既有 `OPENAI_MODEL`、`STARGAZER_SYSTEM_PROMPT` 相同的默认 Profile。工作台切换 Profile 会新建会话；服务端也会把 Profile 标识持久化到 SQLite，拒绝把已有会话改绑到另一个 Profile。

## 业务 Skill

设置 `STARGAZER_SKILLS_DIR` 后，目录的每个一级子目录都可以直接承接为一个业务 Agent。每个子目录中的 `SKILL.md` 会被加载成一个可在工作台选择的 Profile，首次发送消息后会与会话绑定。

```powershell
$env:STARGAZER_SKILLS_DIR = ".\examples\skills"
```

```text
examples/skills/
└── order-support/
    └── SKILL.md
```

```md
---
name: Order Support
model: gpt-4.1-mini
historyLimit: 16
---

You are an order support assistant.
Never invent an order status.
```

`model` 和 `historyLimit` 是可选字段，前者默认使用 `OPENAI_MODEL`。Skill 文件只接受 `name`、`model` 和 `historyLimit` 三个元数据字段；正文是系统提示。Skill 不会自动获得工具权限，仍需由服务端通过 `ToolRegistry` 显式注册。

构建后运行 Web 服务：

```powershell
npm run build
npm start
```

## CLI

发送单条消息：

```powershell
npm run dev -- chat --message "请用三点解释 TypeScript 的 async/await"
```

进入交互式会话：

```powershell
npm run dev -- chat --system-prompt "回答要简洁"
```

输入 `/exit` 或 `/quit` 退出。`--model` 和 `--base-url` 覆盖相应环境变量；`--session-id` 区分同一进程内的会话。进程退出后历史会清空。

构建后也可直接运行 CLI：

```powershell
npm run build
node dist/cli.js chat --message "你好"
```

## 项目结构

```text
src/
├── chat/          消息、模型与会话存储契约、内存替身、ChatAgent 编排
├── memory/        SQLite 会话存储基础设施实现
├── providers/     OpenAI 兼容客户端和离线 Fake Model
├── skills/        SKILL.md 加载与业务 Agent Profile 映射
├── tools/         Tool 契约、白名单注册表与受控执行边界
├── cli.ts         命令行参数、环境变量和终端交互
└── web.ts         Web API、静态资源服务与环境配置
web/
├── index.html         Vite 页面入口
├── vite.config.ts     Vue 构建、开发服务器和 API 代理
├── vitest.config.ts   浏览器端测试环境
└── src/
    ├── components/    工作台布局与聊天组件
    ├── composables/   Agent 状态等组合式逻辑
    ├── services/      Web API 客户端
    ├── stores/        Pinia 会话状态与异步请求编排
    ├── styles/        全局样式和设计 token
    ├── utils/         持久化、Markdown 与通用工具
    ├── App.vue        工作台根组件
    └── main.ts        Vue 应用入口

test/
├── chat/          连续会话与失败边界测试
├── providers/     模型协议与错误脱敏测试
└── web.test.ts    Web API 与静态资源服务测试
```

```text
Web -> ChatAgent -> OpenAICompatibleChatModel -> 模型服务
       |
       +-> ConversationStore -> SqliteConversationStore

CLI -> ChatAgent -> InMemoryConversationStore
```

`chat` 不依赖 HTTP 或数据库，`memory` 只实现会话存储，`providers` 不保存会话，`cli` 不保存密钥。这些边界使后续增加其他模型供应商或存储实现时不会影响对话核心。

## Tool 扩展

业务能力通过服务端代码显式注册。模型只能请求已注册的 Tool，不能自行获得任意文件、命令或网络权限。每轮工具调用有默认上限，Tool 的异常和无效参数会转换为本轮模型可处理的结果，最终会话历史只保存用户消息和最终回答。

```ts
import { ChatAgent } from './src/chat/index.js';
import { ToolRegistry } from './src/tools/index.js';

const tools = new ToolRegistry([
  {
    name: 'lookup_order',
    description: 'Returns the status for one order number.',
    parameters: { type: 'object', properties: { orderId: { type: 'string' } } },
    execute: async (input) => JSON.stringify(await loadOrderStatus(input)),
  },
]);

const agent = new ChatAgent({ model, tools });
```

## 已知边界

- Web 会话持久化限定为单进程 SQLite，不支持多进程共享写入或用户账号隔离。
- 只支持非流式纯文本回复。
- Web API 会串行处理同一会话的请求，但不自动重试；可在创建 Agent 时设置历史消息窗口。

这些是当前最小可用版本的主动取舍；后续能力应基于真实使用场景逐项加入。
