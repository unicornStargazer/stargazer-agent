/** 对话领域服务：组装上下文、调用模型，并以完整轮次写入会话存储。 */

import type { ConversationStore } from './conversation-store.js';
import { InMemoryConversationStore } from './in-memory-conversation-store.js';
import {
  createAssistantMessage,
  createChatMessage,
  createToolCallMessage,
  createToolResultMessage,
} from './models.js';
import type { ChatMessage, ModelTokenUsage, ToolCall } from './models.js';
import type { ChatModel, ModelStreamEvent } from './port.js';
import { ToolRegistry } from '../tools/tool-registry.js';

const DEFAULT_MAXIMUM_TOOL_ROUNDS = 4;

export interface ChatAgentOptions {
  readonly model: ChatModel;
  readonly conversationStore?: ConversationStore | undefined;
  readonly systemPrompt?: string | undefined;
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

  async chat(sessionId: string, text: string): Promise<ChatMessage> {
    const turn = await this.createTurn(sessionId, text);
    const assistantMessage = createAssistantMessage(
      await this.complete(turn.requestMessages, sessionId),
    );
    await this.persistTurn(sessionId, turn.userMessage, assistantMessage);
    return assistantMessage;
  }

  async *chatStream(sessionId: string, text: string): AsyncGenerator<ModelStreamEvent> {
    const turn = await this.createTurn(sessionId, text);

    if (this.tools.isEmpty() && this.model.stream !== undefined) {
      yield* this.streamTurn(sessionId, turn.userMessage, turn.requestMessages);
      return;
    }

    const assistantMessage = createAssistantMessage(
      await this.complete(turn.requestMessages, sessionId),
    );
    await this.persistTurn(sessionId, turn.userMessage, assistantMessage);
    yield { type: 'content', content: assistantMessage.content };
  }

  async history(sessionId: string): Promise<readonly ChatMessage[]> {
    return this.conversationStore.messages(sessionId);
  }

  async clearHistory(sessionId: string): Promise<void> {
    await this.conversationStore.clear(sessionId);
  }

  private async createTurn(sessionId: string, text: string): Promise<ConversationTurn> {
    const userMessage = createChatMessage('user', text);
    const history = await this.conversationStore.messages(sessionId, this.historyLimit);
    const systemMessages =
      this.systemPrompt === undefined ? [] : [createChatMessage('system', this.systemPrompt)];
    return { userMessage, requestMessages: [...systemMessages, ...history, userMessage] };
  }

  private async *streamTurn(
    sessionId: string,
    userMessage: ChatMessage,
    requestMessages: readonly ChatMessage[],
  ): AsyncGenerator<ModelStreamEvent> {
    let content = '';
    let reasoning = '';
    let usage: ModelTokenUsage | undefined;
    for await (const event of this.model.stream!(requestMessages)) {
      if (event.type === 'content') {
        content += event.content;
      }
      if (event.type === 'reasoning') {
        reasoning += event.content;
      }
      if (event.type === 'usage') {
        usage = event.usage;
      }
      yield event;
    }
    await this.persistTurn(
      sessionId,
      userMessage,
      createAssistantMessage(content, reasoning || undefined, usage),
    );
  }

  private async complete(messages: readonly ChatMessage[], sessionId: string): Promise<string> {
    if (this.tools.isEmpty() || this.model.completeWithTools === undefined) {
      return this.model.complete(messages);
    }

    // 工具调用会修改本次请求上下文，不能污染调用方传入的历史消息数组。
    const requestMessages = [...messages];
    for (let round = 0; round < this.maximumToolRounds; round += 1) {
      const completion = await this.model.completeWithTools(
        requestMessages,
        this.tools.definitions(),
      );
      if (completion.toolCalls.length === 0) {
        return completion.content;
      }
      await this.appendToolResults(requestMessages, completion.toolCalls, sessionId);
    }
    // 防止模型持续要求工具调用而形成无界循环。
    throw new Error(`Tool call limit (${String(this.maximumToolRounds)}) exceeded.`);
  }

  /** 工具调用仅参与当前模型上下文，不作为最终会话历史持久化。 */
  private async appendToolResults(
    requestMessages: ChatMessage[],
    toolCalls: readonly ToolCall[],
    sessionId: string,
  ): Promise<void> {
    requestMessages.push(createToolCallMessage(toolCalls));
    for (const toolCall of toolCalls) {
      const result = await this.tools.execute(toolCall.name, toolCall.arguments, { sessionId });
      requestMessages.push(createToolResultMessage(toolCall.id, toolCall.name, result));
    }
  }

  private async persistTurn(
    sessionId: string,
    userMessage: ChatMessage,
    assistantMessage: ChatMessage,
  ): Promise<void> {
    await this.conversationStore.append(sessionId, [userMessage, assistantMessage]);
  }
}

interface ConversationTurn {
  readonly userMessage: ChatMessage;
  readonly requestMessages: readonly ChatMessage[];
}

function normalizeSystemPrompt(value: string | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const systemPrompt = value.trim();
  if (!systemPrompt) {
    throw new Error('系统提示不能为空');
  }
  return systemPrompt;
}

function normalizeHistoryLimit(value: number | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new RangeError('历史消息窗口必须是大于零的安全整数');
  }
  return value;
}

function normalizeMaximumToolRounds(value: number | undefined): number {
  const maximumToolRounds = value ?? DEFAULT_MAXIMUM_TOOL_ROUNDS;
  if (!Number.isSafeInteger(maximumToolRounds) || maximumToolRounds < 1) {
    throw new RangeError('Maximum tool rounds must be a positive safe integer.');
  }
  return maximumToolRounds;
}
