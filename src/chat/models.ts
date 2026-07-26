/**
 * 定义最小文本对话消息。
 *
 * 负责规范化角色和文本；不表示附件、工具调用或供应商专有字段。仅依赖 TypeScript 标准能力。
 */

export type ChatRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ToolCall {
  readonly id: string;
  readonly name: string;
  readonly arguments: string;
}

export interface ChatMessage {
  readonly role: ChatRole;
  readonly content: string;
  readonly toolCalls?: readonly ToolCall[] | undefined;
  readonly toolCallId?: string | undefined;
  readonly name?: string | undefined;
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

/** Creates a transient assistant message that asks the provider to execute tools. */
export function createToolCallMessage(toolCalls: readonly ToolCall[]): ChatMessage {
  if (toolCalls.length === 0) {
    throw new Error('At least one tool call is required.');
  }
  return { role: 'assistant', content: '', toolCalls };
}

/** Creates a transient tool result message for the next model request. */
export function createToolResultMessage(
  toolCallId: string,
  name: string,
  content: string,
): ChatMessage {
  if (!toolCallId.trim() || !name.trim()) {
    throw new Error('Tool call ID and tool name are required.');
  }
  if (!content.trim()) {
    throw new Error('Tool result cannot be empty.');
  }
  return { role: 'tool', content, toolCallId, name };
}
