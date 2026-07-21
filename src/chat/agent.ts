/**
 * 实现最小文本对话编排。
 *
 * 负责组装系统提示、当前进程的会话历史和用户输入，并在模型成功后保存完整轮次；不负责
 * HTTP 协议、工具选择、审批、长期记忆或持久化。仅依赖 chat 域内接口和模型。
 */

import { InMemoryConversationStore } from './conversation.js';
import { createChatMessage } from './models.js';
import type { ChatMessage } from './models.js';
import type { ChatModel } from './port.js';

export interface ChatAgentOptions {
  readonly model: ChatModel;
  readonly conversationStore?: InMemoryConversationStore | undefined;
  readonly systemPrompt?: string | undefined;
}

export class ChatAgent {
  private readonly model: ChatModel;
  private readonly conversationStore: InMemoryConversationStore;
  private readonly systemPrompt: string | undefined;

  constructor(options: ChatAgentOptions) {
    this.model = options.model;
    this.conversationStore = options.conversationStore ?? new InMemoryConversationStore();
    this.systemPrompt = normalizeSystemPrompt(options.systemPrompt);
  }

  /** 完成一轮对话，并只在模型成功且回复有效后写入用户和助手消息。 */
  async chat(sessionId: string, text: string): Promise<ChatMessage> {
    const userMessage = createChatMessage('user', text);
    const requestMessages = this.buildRequest(sessionId, userMessage);
    const responseText = await this.model.complete(requestMessages);
    const assistantMessage = createChatMessage('assistant', responseText);
    this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
    return assistantMessage;
  }

  /** 读取进程内会话中的用户和助手消息，不包含每轮注入的系统提示。 */
  history(sessionId: string): readonly ChatMessage[] {
    return this.conversationStore.messages(sessionId);
  }

  private buildRequest(sessionId: string, userMessage: ChatMessage): readonly ChatMessage[] {
    const history = this.conversationStore.messages(sessionId);
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
