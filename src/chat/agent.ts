/**
 * 编排一次完整的文本对话。
 *
 * ChatAgent 只依赖模型和会话存储契约，不知道 HTTP、SQLite、Tool 或长期记忆的存在。
 */

import type { ConversationStore } from './conversation-store.js';
import { InMemoryConversationStore } from './in-memory-conversation-store.js';
import { createChatMessage } from './models.js';
import type { ChatMessage } from './models.js';
import type { ChatModel } from './port.js';

export interface ChatAgentOptions {
  readonly model: ChatModel;
  readonly conversationStore?: ConversationStore | undefined;
  readonly systemPrompt?: string | undefined;
  /** 限制送入模型的最近历史消息数量；不影响 history() 返回的完整会话。 */
  readonly historyLimit?: number | undefined;
}

export class ChatAgent {
  private readonly model: ChatModel;
  private readonly conversationStore: ConversationStore;
  private readonly systemPrompt: string | undefined;
  private readonly historyLimit: number | undefined;

  constructor(options: ChatAgentOptions) {
    this.model = options.model;
    this.conversationStore = options.conversationStore ?? new InMemoryConversationStore();
    this.systemPrompt = normalizeSystemPrompt(options.systemPrompt);
    this.historyLimit = normalizeHistoryLimit(options.historyLimit);
  }

  /**
   * 聊天方法，处理用户输入并返回助手的回复
   * @param sessionId 会话ID，用于标识当前对话
   * @param text 用户输入的文本内容
   * @returns 返回一个Promise，解析为ChatMessage类型的助手回复消息
   */
  async chat(sessionId: string, text: string): Promise<ChatMessage> {
    // 创建用户消息对象
    const userMessage = createChatMessage('user', text);
    // 构建请求消息列表，包含对话历史和当前用户消息
    const requestMessages = await this.buildRequest(sessionId, userMessage);
    // 调用模型获取回复文本
    const responseText = await this.model.complete(requestMessages);
    // 创建助手消息对象
    const assistantMessage = createChatMessage('assistant', responseText);
    // 将用户消息和助手消息保存到会话存储中
    await this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
    // 返回助手消息
    return assistantMessage;
  }

  /** 逐段返回模型文本，并仅在正常结束后持久化完整轮次。 */
  async *chatStream(sessionId: string, text: string): AsyncGenerator<string> {
    const userMessage = createChatMessage('user', text);
    const requestMessages = await this.buildRequest(sessionId, userMessage);
    if (this.model.stream === undefined) {
      const response = await this.chat(sessionId, text);
      yield response.content;
      return;
    }
    let content = '';
    for await (const chunk of this.model.stream(requestMessages)) {
      if (!chunk) continue;
      content += chunk;
      yield chunk;
    }
    const assistantMessage = createChatMessage('assistant', content);
    await this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
  }

  /** 返回不包含每轮系统提示的完整服务端会话历史。 */
  async history(sessionId: string): Promise<readonly ChatMessage[]> {
    return this.conversationStore.messages(sessionId);
  }

  /** 删除指定会话；具体存储实现保证删除的持久化语义。 */
  async clearHistory(sessionId: string): Promise<void> {
    await this.conversationStore.clear(sessionId);
  }

  private async buildRequest(
    sessionId: string,
    userMessage: ChatMessage,
  ): Promise<readonly ChatMessage[]> {
    const history = await this.conversationStore.messages(sessionId, this.historyLimit);
    const systemMessages =
      this.systemPrompt === undefined ? [] : [createChatMessage('system', this.systemPrompt)];
    return [...systemMessages, ...history, userMessage];
  }
}

function normalizeSystemPrompt(systemPrompt: string | undefined): string | undefined {
  if (systemPrompt === undefined) {
    return undefined;
  }
  if (typeof systemPrompt !== 'string') {
    throw new TypeError('系统提示必须是字符串');
  }
  const normalizedSystemPrompt = systemPrompt.trim();
  if (!normalizedSystemPrompt) {
    throw new Error('系统提示不能为空');
  }
  return normalizedSystemPrompt;
}

function normalizeHistoryLimit(historyLimit: number | undefined): number | undefined {
  if (historyLimit === undefined) {
    return undefined;
  }
  if (!Number.isSafeInteger(historyLimit) || historyLimit < 1) {
    throw new RangeError('历史消息窗口必须是大于零的安全整数');
  }
  return historyLimit;
}
