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

/**
 * 聊天代理类，用于管理对话流程和维护对话历史
 */
export class ChatAgent {
  // 私有属性：聊天模型
  private readonly model: ChatModel;
  // 私有属性：对话存储，用于保存对话历史
  private readonly conversationStore: InMemoryConversationStore;
  // 私有属性：系统提示词，用于设定AI的行为和角色
  private readonly systemPrompt: string | undefined;

  /**
   * 构造函数，初始化聊天代理
   * @param options 配置选项，包含模型、对话存储和系统提示
   */
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

  /** 清除当前进程内的指定会话历史。 */
  clearHistory(sessionId: string): void {
    this.conversationStore.clear(sessionId);
  }

  /**
   * 构建聊天请求消息列表
   * @param sessionId 会话ID，用于标识特定的对话会话
   * @param userMessage 用户发送的消息对象
   * @returns 返回一个只读的聊天消息数组，包含系统消息、历史消息和用户消息
   */
  private buildRequest(sessionId: string, userMessage: ChatMessage): readonly ChatMessage[] {
    // 从对话存储中获取指定会话的历史消息
    const history = this.conversationStore.messages(sessionId);
    // 如果系统提示存在，则创建系统消息；否则为空数组
    const systemMessages =
      this.systemPrompt === undefined ? [] : [createChatMessage('system', this.systemPrompt)];
    // 将系统消息、历史消息和用户消息合并并返回
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
