/**
 * 提供进程内的最小会话历史存储。
 *
 * 负责按会话标识保存用户和助手消息；不负责持久化、摘要、向量检索或并发顺序控制。
 * 仅依赖消息类型和 JavaScript 标准集合。
 */

import type { ChatMessage } from './models.js';

export class InMemoryConversationStore {
  private readonly messagesBySession = new Map<string, ChatMessage[]>();

  /** 返回会话快照；未知会话返回空数组，调用方不能修改内部历史。 */
  messages(sessionId: string): readonly ChatMessage[] {
    const messages = this.messagesBySession.get(normalizeSessionId(sessionId));
    return messages === undefined ? [] : [...messages];
  }

  /** 按给定顺序追加完整对话轮次；空数组不改变会话。 */
  append(sessionId: string, messages: readonly ChatMessage[]): void {
    if (messages.length === 0) {
      return;
    }
    const normalizedSessionId = normalizeSessionId(sessionId);
    const currentMessages = this.messagesBySession.get(normalizedSessionId) ?? [];
    currentMessages.push(...messages);
    this.messagesBySession.set(normalizedSessionId, currentMessages);
  }

  /** 清除指定会话；未知会话按幂等成功处理。 */
  clear(sessionId: string): void {
    this.messagesBySession.delete(normalizeSessionId(sessionId));
  }
}

function normalizeSessionId(sessionId: string): string {
  if (typeof sessionId !== 'string') {
    throw new TypeError('会话标识必须是字符串');
  }
  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) {
    throw new Error('会话标识不能为空');
  }
  return normalizedSessionId;
}
