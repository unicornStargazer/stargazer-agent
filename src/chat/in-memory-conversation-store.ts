/**
 * 提供 ConversationStore 的进程内实现。
 *
 * 它用于测试和短生命周期 CLI；不负责跨进程恢复、事务日志或长期记忆。
 */

import {
  normalizeConversationMessageLimit,
  normalizeConversationSessionId,
} from './conversation-store.js';
import type { ConversationStore } from './conversation-store.js';
import type { ChatMessage } from './models.js';

export class InMemoryConversationStore implements ConversationStore {
  private readonly messagesBySession = new Map<string, ChatMessage[]>();

/**
 * 获取指定会话的消息列表
 * @param sessionId 会话ID，用于标识特定的对话会话
 * @param limit 可选参数，限制返回的消息数量
 * @returns 返回一个Promise，解析为只读的ChatMessage数组
 */
  messages(sessionId: string, limit?: number): Promise<readonly ChatMessage[]> {
    // 标准化会话ID，确保ID格式统一
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    // 标准化消息数量限制，确保数值有效
    const normalizedLimit = normalizeConversationMessageLimit(limit);
    // 从会话消息映射中获取消息列表，如果不存在则返回空数组
    const messages = this.messagesBySession.get(normalizedSessionId) ?? [];
    // 根据限制参数决定返回全部消息或最后N条消息
    const visibleMessages =
      normalizedLimit === undefined ? messages : messages.slice(-normalizedLimit);
    // 将消息数组转换为新的数组实例，并作为Promise的结果返回
    return Promise.resolve([...visibleMessages]);
  }

/**
 * 向指定会话追加消息的方法
 * @param sessionId - 会话ID，用于标识特定的对话会话
 * @param messages - 要追加的消息数组，使用ChatMessage类型，且为只读数组
 * @returns 返回一个Promise，解析为void类型
 */
  append(sessionId: string, messages: readonly ChatMessage[]): Promise<void> {
    // 如果消息数组为空，直接返回已解析的Promise
    if (messages.length === 0) {
      return Promise.resolve();
    }
    // 规范化会话ID以确保一致性
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    // 获取当前会话的消息列表，如果不存在则创建空数组
    const currentMessages = this.messagesBySession.get(normalizedSessionId) ?? [];
    // 将新消息添加到当前消息列表中
    currentMessages.push(...messages);
    // 更新会话的消息列表
    this.messagesBySession.set(normalizedSessionId, currentMessages);
    // 返回已解析的Promise
    return Promise.resolve();
  }

  clear(sessionId: string): Promise<void> {
    this.messagesBySession.delete(normalizeConversationSessionId(sessionId));
    return Promise.resolve();
  }
}
