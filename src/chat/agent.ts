/**
 * 编排一次完整的文本对话。
 *
 * ChatAgent 只依赖模型和会话存储契约，不知道 HTTP、SQLite、Tool 或长期记忆的存在。
 */

import type { ConversationStore } from './conversation-store.js';
import { InMemoryConversationStore } from './in-memory-conversation-store.js';
import { createChatMessage, createToolCallMessage, createToolResultMessage } from './models.js';
import type { ChatMessage } from './models.js';
import type { ChatModel } from './port.js';
import { ToolRegistry } from '../tools/tool-registry.js';

const DEFAULT_MAXIMUM_TOOL_ROUNDS = 4;

export interface ChatAgentOptions {
  readonly model: ChatModel;
  readonly conversationStore?: ConversationStore | undefined;
  readonly systemPrompt?: string | undefined;
  /** 限制送入模型的最近历史消息数量；不影响 history() 返回的完整会话。 */
  readonly historyLimit?: number | undefined;
  readonly tools?: ToolRegistry | undefined;
  readonly maximumToolRounds?: number | undefined;
}

export class ChatAgent {
  private readonly model: ChatModel;
  private readonly conversationStore: ConversationStore;
  private readonly systemPrompt: string | undefined;
  private readonly historyLimit: number | undefined;
  private readonly tools: ToolRegistry;
  private readonly maximumToolRounds: number;

  constructor(options: ChatAgentOptions) {
    this.model = options.model;
    this.conversationStore = options.conversationStore ?? new InMemoryConversationStore();
    this.systemPrompt = normalizeSystemPrompt(options.systemPrompt);
    this.historyLimit = normalizeHistoryLimit(options.historyLimit);
    this.tools = options.tools ?? new ToolRegistry();
    this.maximumToolRounds = normalizeMaximumToolRounds(options.maximumToolRounds);
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
    const responseText = await this.complete(requestMessages, sessionId);
    // 创建助手消息对象
    const assistantMessage = createChatMessage('assistant', responseText);
    // 将用户消息和助手消息保存到会话存储中
    await this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
    // 返回助手消息
    return assistantMessage;
  }

  /**
   * 聊天流生成器函数，用于生成聊天内容的异步流
   * @param sessionId 会话ID，用于标识当前对话
   * @param text 用户输入的文本内容
   * @returns 返回一个异步生成器，用于逐步产生聊天响应
   */
  async *chatStream(sessionId: string, text: string): AsyncGenerator<string> {
    // 创建用户消息对象
    const userMessage = createChatMessage('user', text);
    // 构建请求消息列表，包含会话历史和当前用户消息
    const requestMessages = await this.buildRequest(sessionId, userMessage);
    // 如果启用了工具功能
    if (!this.tools.isEmpty()) {
      // 获取完整响应
      const response = await this.complete(requestMessages, sessionId);
      // 创建助手消息对象
      const assistantMessage = createChatMessage('assistant', response);
      // 将用户和助手消息添加到会话存储中
      await this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
      // 返回完整响应
      yield response;
      return;
    }
    // 如果模型不支持流式响应
    if (this.model.stream === undefined) {
      // 获取聊天响应
      const response = await this.chat(sessionId, text);
      // 返回响应内容
      yield response.content;
      return;
    }
    let content = ''; // 用于累积流式响应的内容
    // 遍历流式响应的每个数据块
    for await (const chunk of this.model.stream(requestMessages)) {
      // 如果数据块为空则跳过
      if (!chunk) continue;
      // 累积内容
      content += chunk;
      // 产出当前数据块
      yield chunk;
    }
    // 创建助手消息对象
    const assistantMessage = createChatMessage('assistant', content);
    // 将用户和助手消息添加到会话存储中
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

  /**
   * 使用工具完成对话的私有异步方法
   * @param messages - 聊天消息的只读数组
   * @param sessionId - 会话ID
   * @returns 返回完成的文本内容
   */
  private async complete(messages: readonly ChatMessage[], sessionId: string): Promise<string> {
    // 检查是否有可用工具以及模型是否支持工具完成功能
    if (this.tools.isEmpty() || this.model.completeWithTools === undefined) {
      // 如果没有工具或模型不支持工具完成，直接使用模型完成对话
      return this.model.complete(messages);
    }

    // 创建请求消息的副本，用于迭代处理
    const requestMessages = [...messages];
    // 最大工具调用轮次的循环处理
    for (let round = 0; round < this.maximumToolRounds; round += 1) {
      // 使用工具调用模型完成对话
      const completion = await this.model.completeWithTools(
        requestMessages,
        this.tools.definitions(),
      );
      // 如果没有工具调用，直接返回完成的内容
      if (completion.toolCalls.length === 0) {
        return completion.content;
      }
      // 添加工具调用消息到请求消息列表
      requestMessages.push(createToolCallMessage(completion.toolCalls));
      // 执行所有工具调用并处理结果
      for (const toolCall of completion.toolCalls) {
        // 执行工具调用并传入会话ID
        const result = await this.tools.execute(toolCall.name, toolCall.arguments, { sessionId });
        // 添加工具执行结果到请求消息列表
        requestMessages.push(createToolResultMessage(toolCall.id, toolCall.name, result));
      }
    }
    // 如果超过最大工具调用轮次，抛出错误
    throw new Error(`Tool call limit (${String(this.maximumToolRounds)}) exceeded.`);
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

function normalizeMaximumToolRounds(maximumToolRounds: number | undefined): number {
  const value = maximumToolRounds ?? DEFAULT_MAXIMUM_TOOL_ROUNDS;
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new RangeError('Maximum tool rounds must be a positive safe integer.');
  }
  return value;
}
