/**
 * 暴露标准文本对话核心的稳定入口。
 *
 * 负责统一导出消息、模型端口、会话存储与 Agent；不导出供应商实现或 CLI 细节。
 */

export { ChatAgent } from './agent.js';
export { InMemoryConversationStore } from './conversation.js';
export { createChatMessage } from './models.js';
export type { ChatMessage, ChatRole } from './models.js';
export type { ChatModel } from './port.js';
