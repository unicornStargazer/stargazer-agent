/**
 * 暴露模型供应商适配的稳定入口。
 *
 * 负责导出 OpenAI 兼容客户端和离线测试替身；不负责会话保存或 CLI 参数解析。
 */

export { FakeChatModel } from './fake-chat-model.js';
export { OpenAICompatibleChatModel, OpenAICompatibleError } from './openai-compatible.js';
export type { FetchImplementation, OpenAICompatibleConfig } from './openai-compatible.js';
