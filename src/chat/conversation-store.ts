/**
 * 定义对话历史的持久化契约。
 *
 * 该模块只描述会话消息的读取、完整轮次追加与删除语义；不绑定数据库、HTTP 或模型供应商。
 */

import type { ChatMessage } from './models.js';

export interface ConversationStore {
  /**
   * 按写入顺序读取会话消息。指定 limit 时返回最近的消息，但返回结果仍保持时间正序。
   * 存储不可用时必须拒绝 Promise，调用方不能将其误当作空历史。
   */
  messages(sessionId: string, limit?: number): Promise<readonly ChatMessage[]>;

  /**
   * 原子追加一批消息。调用方用它保存完整对话轮次，失败时不得留下部分消息。
   */
  append(sessionId: string, messages: readonly ChatMessage[]): Promise<void>;

  /** 删除会话及其全部消息；未知会话按幂等成功处理。 */
  clear(sessionId: string): Promise<void>;
}

/**
 * 为需要按 Profile 隔离上下文的存储实现提供可选元数据能力。
 *
 * Profile 不属于聊天消息本身，因此不放进 ChatMessage；调用方在首轮聊天前绑定它，
 * 后续只能读取相同标识，避免同一历史被不同系统提示重新解释。
 */
export interface ConversationProfileStore extends ConversationStore {
  profileId(sessionId: string): Promise<string | undefined>;
  bindProfile(sessionId: string, profileId: string): Promise<void>;
}

/** 表示存储层故障，Web 适配器可据此避免把数据库异常伪装成模型异常。 */
export class ConversationStoreError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = 'ConversationStoreError';
  }
}

/** 统一校验会话标识，避免不同存储实现对空白会话产生不同语义。 */
export function normalizeConversationSessionId(sessionId: string): string {
  if (typeof sessionId !== 'string') {
    throw new TypeError('会话标识必须是字符串');
  }
  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) {
    throw new Error('会话标识不能为空');
  }
  return normalizedSessionId;
}

/** 验证可选窗口大小，防止实现层把非法值传递给查询参数。 */
export function normalizeConversationMessageLimit(limit: number | undefined): number | undefined {
  if (limit === undefined) {
    return undefined;
  }
  if (!Number.isSafeInteger(limit) || limit < 1) {
    throw new RangeError('消息窗口必须是大于零的安全整数');
  }
  return limit;
}
