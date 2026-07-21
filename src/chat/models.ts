/**
 * 定义最小文本对话消息。
 *
 * 负责规范化角色和文本；不表示附件、工具调用或供应商专有字段。仅依赖 TypeScript 标准能力。
 */

export type ChatRole = 'system' | 'user' | 'assistant';

export interface ChatMessage {
  readonly role: ChatRole;
  readonly content: string;
}

/** 创建可安全发送给模型或写入会话的非空文本消息。 */
export function createChatMessage(role: ChatRole, content: string): ChatMessage {
  if (typeof content !== 'string') {
    throw new TypeError('消息内容必须是字符串');
  }
  const normalizedContent = content.trim();
  if (!normalizedContent) {
    throw new Error('消息内容不能为空');
  }
  return { role, content: normalizedContent };
}
