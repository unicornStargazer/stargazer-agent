/**
 * ConversationStore 的进程内实现。
 *
 * 它用于测试和短生命周期运行；不提供跨进程恢复、事务日志或长期记忆能力。
 */

import {
  normalizeConversationMessageLimit,
  normalizeConversationSessionId,
} from './conversation-store.js';
import type { ConversationProfileStore } from './conversation-store.js';
import type { ChatMessage } from './models.js';

export class InMemoryConversationStore implements ConversationProfileStore {
  private readonly messagesBySession = new Map<string, ChatMessage[]>();
  private readonly profileBySession = new Map<string, string>();

  messages(sessionId: string, limit?: number): Promise<readonly ChatMessage[]> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    const normalizedLimit = normalizeConversationMessageLimit(limit);
    const messages = this.messagesBySession.get(normalizedSessionId) ?? [];
    const visibleMessages =
      normalizedLimit === undefined ? messages : messages.slice(-normalizedLimit);

    // 返回副本，调用方不能通过数组操作修改存储中的会话历史。
    return Promise.resolve([...visibleMessages]);
  }

  append(sessionId: string, messages: readonly ChatMessage[]): Promise<void> {
    if (messages.length === 0) {
      return Promise.resolve();
    }

    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    const currentMessages = this.messagesBySession.get(normalizedSessionId) ?? [];
    currentMessages.push(...messages);
    this.messagesBySession.set(normalizedSessionId, currentMessages);
    return Promise.resolve();
  }

  clear(sessionId: string): Promise<void> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    this.messagesBySession.delete(normalizedSessionId);
    this.profileBySession.delete(normalizedSessionId);
    return Promise.resolve();
  }

  profileId(sessionId: string): Promise<string | undefined> {
    return Promise.resolve(this.profileBySession.get(normalizeConversationSessionId(sessionId)));
  }

  bindProfile(sessionId: string, profileId: string): Promise<void> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    const normalizedProfileId = normalizeConversationSessionId(profileId);
    const existingProfileId = this.profileBySession.get(normalizedSessionId);
    if (existingProfileId !== undefined && existingProfileId !== normalizedProfileId) {
      return Promise.reject(new Error('会话已绑定其他 Profile'));
    }
    this.profileBySession.set(normalizedSessionId, normalizedProfileId);
    return Promise.resolve();
  }
}
