# Stargazer Agent

Stargazer Agent 是一个可快速运行的 TypeScript 文本对话 Agent。它在当前进程内保存会话历史，并通过 OpenAI 兼容的 `/chat/completions` 接口调用模型。

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

## 快速开始

密钥只从环境变量读取，不要把它写入源码或提交到仓库。

```powershell
$env:OPENAI_API_KEY = "你的密钥"
$env:OPENAI_MODEL = "gpt-4.1-mini"
# 可选，默认 https://api.openai.com/v1
$env:OPENAI_BASE_URL = "https://api.openai.com/v1"
```

发送单条消息：

```powershell
npm run dev -- chat --message "请用三点解释 TypeScript 的 async/await"
```

进入交互式会话：

```powershell
npm run dev -- chat --system-prompt "回答要简洁"
```

输入 `/exit` 或 `/quit` 退出。`--model` 和 `--base-url` 覆盖相应环境变量；`--session-id` 区分同一进程内的会话。进程退出后历史会清空。

构建后可直接运行：

```powershell
npm run build
node dist/cli.js chat --message "你好"
```

## 项目结构

```text
src/
├── chat/          消息、模型端口、内存会话与 ChatAgent 编排
├── providers/     OpenAI 兼容客户端和离线 Fake Model
└── cli.ts         命令行参数、环境变量和终端交互

test/
├── chat/          连续会话与失败边界测试
└── providers/     模型协议与错误脱敏测试
```

```text
CLI -> ChatAgent -> OpenAICompatibleChatModel -> 模型服务
                   |
                   +-> InMemoryConversationStore
```

`chat` 不依赖 HTTP，`providers` 不保存会话，`cli` 不保存密钥。这些边界使后续增加其他模型供应商时不会影响对话核心。

## 已知边界

- 会话历史仅存于当前进程。
- 只支持非流式纯文本回复。
- 不保证同一会话的并发调用顺序，也不自动重试或压缩上下文。

这些是当前最小可用版本的主动取舍；后续能力应基于真实使用场景逐项加入。
