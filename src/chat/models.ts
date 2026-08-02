/**
 * 对话领域消息模型。
 *
 * 除文本外，助手消息可携带已公开的推理文本与模型用量；它们属于展示和审计元数据，
 * Provider 请求只会使用角色、正文和工具调用字段。
 */

export type ChatRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ModelTokenUsage {
  readonly inputTokens?: number | undefined;
  readonly outputTokens?: number | undefined;
  readonly reasoningTokens?: number | undefined;
  readonly totalTokens?: number | undefined;
}

export interface ToolCall {
  readonly id: string;
  readonly name: string;
  readonly arguments: string;
}

export interface ChatMessage {
  readonly role: ChatRole;
  readonly content: string;
  readonly reasoning?: string | undefined;
  readonly usage?: ModelTokenUsage | undefined;
  readonly toolCalls?: readonly ToolCall[] | undefined;
  readonly toolCallId?: string | undefined;
  readonly name?: string | undefined;
}

export function createChatMessage(role: ChatRole, content: string): ChatMessage {
  return { role, content: normalizeContent(content) };
}

/**
 * 创建可被持久化的助手消息。推理文本和用量仅允许附着在助手消息上，
 * 防止用户输入伪造模型统计信息。
 */
export function createAssistantMessage(
  content: string,
  reasoning?: string,
  usage?: ModelTokenUsage,
): ChatMessage {
  const normalizedReasoning = reasoning?.trim() || undefined;
  return {
    role: 'assistant',
    content: normalizeContent(content),
    ...(normalizedReasoning === undefined ? {} : { reasoning: normalizedReasoning }),
    ...(usage === undefined ? {} : { usage: normalizeTokenUsage(usage) }),
  };
}

/**
 * 创建仅供当前模型请求使用的工具调用消息。
 * 它不会写入会话历史，避免下一轮对话携带无法重新执行的旧工具调用。
 */
export function createToolCallMessage(toolCalls: readonly ToolCall[]): ChatMessage {
  if (toolCalls.length === 0) {
    throw new Error('At least one tool call is required.');
  }
  return { role: 'assistant', content: '', toolCalls };
}

/** 创建与工具调用 ID 对应的临时结果消息，供模型继续组织最终回复。 */
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

function normalizeContent(content: string): string {
  if (typeof content !== 'string') {
    throw new TypeError('消息内容必须是字符串');
  }
  const normalizedContent = content.trim();
  if (!normalizedContent) {
    throw new Error('消息内容不能为空');
  }
  return normalizedContent;
}

function normalizeTokenUsage(usage: ModelTokenUsage): ModelTokenUsage {
  return {
    inputTokens: normalizeTokenCount(usage.inputTokens, 'inputTokens'),
    outputTokens: normalizeTokenCount(usage.outputTokens, 'outputTokens'),
    reasoningTokens: normalizeTokenCount(usage.reasoningTokens, 'reasoningTokens'),
    totalTokens: normalizeTokenCount(usage.totalTokens, 'totalTokens'),
  };
}

function normalizeTokenCount(value: number | undefined, fieldName: string): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Token 用量字段 ${fieldName} 必须是非负整数`);
  }
  return value;
}
