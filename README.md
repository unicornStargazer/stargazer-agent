# Stargazer Agent

Stargazer Agent 是一个可快速运行的 TypeScript 文本对话 Agent，提供浏览器工作台和 CLI 两种入口。它在当前进程内保存会话历史，并通过 OpenAI 兼容的 `/chat/completions` 接口调用模型。

当前只实现“连续文本对话”这个核心能力，不包含 Tool、Policy、审批、长期记忆、持久化、流式响应、多 Agent 或复杂运行时。

## 环境

- Node.js 22 LTS
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

页面提供多会话导航、安全 Markdown 与代码块展示、复制、失败重试和移动端布局。浏览器保存会话列表和页面消息，模型上下文仍遵循后端约束，仅保存在当前服务进程中；删除会话时会同时清除两侧记录。

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
├── chat/          消息、模型端口、内存会话与 ChatAgent 编排
├── providers/     OpenAI 兼容客户端和离线 Fake Model
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
Web/CLI -> ChatAgent -> OpenAICompatibleChatModel -> 模型服务
                       |
                       +-> InMemoryConversationStore
```

`chat` 不依赖 HTTP，`providers` 不保存会话，`cli` 不保存密钥。这些边界使后续增加其他模型供应商时不会影响对话核心。

## 已知边界

- 会话历史仅存于当前进程。
- 只支持非流式纯文本回复。
- Web API 会串行处理同一会话的请求，但不自动重试或压缩上下文。

这些是当前最小可用版本的主动取舍；后续能力应基于真实使用场景逐项加入。
