/**
 * OpenAI Chat Completions 协议适配器。
 *
 * 该模块只负责模型供应商协议：构造请求、执行 HTTP 调用和解析响应。
 * 会话编排、重试策略与持久化属于上层，不应进入 Provider。
 */

import type {
  ChatMessage,
  ChatModel,
  ModelStreamEvent,
  ModelTokenUsage,
  ToolCall,
  ToolCallingCompletion,
} from '../chat/index.js';
import type { ToolDefinition } from '../tools/index.js';

const DEFAULT_BASE_URL = 'https://api.openai.com/v1';
const DEFAULT_TIMEOUT_MS = 60_000;

export interface OpenAICompatibleConfig {
  readonly apiKey: string;
  readonly model: string;
  readonly baseUrl?: string | undefined;
  readonly timeoutMs?: number | undefined;
  readonly includeStreamUsage?: boolean | undefined;
}

export type FetchImplementation = typeof fetch;

interface ValidatedConfig {
  readonly apiKey: string;
  readonly model: string;
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly includeStreamUsage: boolean;
}

interface CompletionRequest {
  readonly messages: readonly ChatMessage[];
  readonly stream: boolean;
  readonly tools: readonly ToolDefinition[];
}

export class OpenAICompatibleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OpenAICompatibleError';
  }
}

export class OpenAICompatibleChatModel implements ChatModel {
  private readonly config: ValidatedConfig;
  private readonly fetchImplementation: FetchImplementation;

  constructor(config: OpenAICompatibleConfig, fetchImplementation: FetchImplementation = fetch) {
    this.config = validateConfig(config);
    this.fetchImplementation = fetchImplementation;
  }

  async complete(messages: readonly ChatMessage[]): Promise<string> {
    const response = await this.requestCompletion({ messages, stream: false, tools: [] });
    assertSuccessfulResponse(response);
    return extractAssistantText(await parseJsonResponse(response));
  }

  async completeWithTools(
    messages: readonly ChatMessage[],
    tools: readonly ToolDefinition[],
  ): Promise<ToolCallingCompletion> {
    const response = await this.requestCompletion({ messages, stream: false, tools });
    assertSuccessfulResponse(response);
    return extractToolCallingCompletion(await parseJsonResponse(response));
  }

  async *stream(messages: readonly ChatMessage[]): AsyncGenerator<ModelStreamEvent> {
    const response = await this.requestCompletion({ messages, stream: true, tools: [] });
    assertSuccessfulStreamResponse(response);

    for await (const data of readSseData(response.body)) {
      if (data === '[DONE]') {
        return;
      }
      yield* parseStreamEvents(data);
    }
  }

  /**
   * Provider 调用的超时只覆盖单次 HTTP 请求。重试、限流和会话编排属于上层职责，
   * 避免不同 Provider 适配器产生不一致的重试语义。
   */
  private async requestCompletion(request: CompletionRequest): Promise<Response> {
    assertMessagesPresent(request.messages);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    try {
      return await this.fetchImplementation(completionUrl(this.config.baseUrl), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.config.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(this.buildRequestBody(request)),
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new OpenAICompatibleError('模型服务请求超时');
      }
      throw new OpenAICompatibleError('无法连接模型服务');
    } finally {
      clearTimeout(timeoutId);
    }
  }

  private buildRequestBody(request: CompletionRequest): Record<string, unknown> {
    return {
      model: this.config.model,
      messages: request.messages.map(toProviderMessage),
      ...streamOptions(request.stream, this.config.includeStreamUsage),
      ...toolOptions(request.tools),
    };
  }
}

function assertMessagesPresent(messages: readonly ChatMessage[]): void {
  if (messages.length === 0) {
    throw new Error('至少需要一条消息才能调用模型');
  }
}

function assertSuccessfulResponse(response: Response): void {
  if (!response.ok) {
    throw new OpenAICompatibleError(`模型服务返回 HTTP ${response.status}`);
  }
}

function assertSuccessfulStreamResponse(
  response: Response,
): asserts response is Response & { body: ReadableStream<Uint8Array> } {
  assertSuccessfulResponse(response);
  if (response.body === null) {
    throw new OpenAICompatibleError('模型服务未返回流式响应体');
  }
}

function streamOptions(stream: boolean, includeStreamUsage: boolean): Record<string, unknown> {
  if (!stream) {
    return {};
  }
  return {
    stream: true,
    ...(includeStreamUsage ? { stream_options: { include_usage: true } } : {}),
  };
}

function toolOptions(tools: readonly ToolDefinition[]): Record<string, unknown> {
  return tools.length === 0 ? {} : { tools: tools.map(toProviderTool) };
}

async function* readSseData(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      // 网络分块不保证与 SSE 行边界一致，保留最后一个不完整片段等待下一次读取。
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? '';
      yield* dataLines(lines);
    }

    buffer += decoder.decode();
    yield* dataLines([buffer]);
  } finally {
    reader.releaseLock();
  }
}

function* dataLines(lines: readonly string[]): Generator<string> {
  for (const line of lines) {
    if (line.startsWith('data:')) {
      yield line.slice(5).trim();
    }
  }
}

function parseStreamEvents(value: string): readonly ModelStreamEvent[] {
  try {
    const body = requireRecord(JSON.parse(value) as unknown);
    const events: ModelStreamEvent[] = [];
    appendUsageEvent(events, body.usage);
    appendDeltaEvents(events, body.choices);
    return events;
  } catch (error) {
    if (error instanceof OpenAICompatibleError) {
      throw error;
    }
    throw new OpenAICompatibleError('模型流式响应不是有效 JSON');
  }
}

function appendUsageEvent(events: ModelStreamEvent[], value: unknown): void {
  const usage = extractUsage(value);
  if (usage !== undefined) {
    events.push({ type: 'usage', usage });
  }
}

function appendDeltaEvents(events: ModelStreamEvent[], choicesValue: unknown): void {
  const choices = requireArray(choicesValue, '模型流响应缺少 choices');
  const firstChoice = choices.at(0);
  if (firstChoice === undefined) {
    return;
  }

  const choice = requireRecord(firstChoice);
  if (!isRecord(choice.delta)) {
    return;
  }

  const reasoning = extractReasoning(choice.delta);
  if (reasoning !== undefined) {
    events.push({ type: 'reasoning', content: reasoning });
  }
  if (typeof choice.delta.content === 'string' && choice.delta.content) {
    events.push({ type: 'content', content: choice.delta.content });
  }
}

function extractReasoning(delta: Record<string, unknown>): string | undefined {
  const reasoning = delta.reasoning_content ?? delta.reasoning;
  return typeof reasoning === 'string' && reasoning ? reasoning : undefined;
}

function extractUsage(value: unknown): ModelTokenUsage | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  // reasoning_tokens 是部分兼容实现的可选扩展，缺失时不影响常规用量展示。
  const completionDetails = isRecord(value.completion_tokens_details)
    ? value.completion_tokens_details
    : undefined;
  const usage = {
    inputTokens: nonNegativeInteger(value.prompt_tokens),
    outputTokens: nonNegativeInteger(value.completion_tokens),
    reasoningTokens: completionDetails
      ? nonNegativeInteger(completionDetails.reasoning_tokens)
      : undefined,
    totalTokens: nonNegativeInteger(value.total_tokens),
  };
  return Object.values(usage).some((tokenCount) => tokenCount !== undefined) ? usage : undefined;
}

function toProviderMessage(message: ChatMessage): Record<string, unknown> {
  if (message.role === 'tool') {
    return { role: 'tool', content: message.content, tool_call_id: message.toolCallId };
  }
  if (message.toolCalls !== undefined) {
    return {
      role: 'assistant',
      content: message.content || null,
      tool_calls: message.toolCalls.map((toolCall) => ({
        id: toolCall.id,
        type: 'function',
        function: { name: toolCall.name, arguments: toolCall.arguments },
      })),
    };
  }
  return { role: message.role, content: message.content };
}

function toProviderTool(tool: ToolDefinition): Record<string, unknown> {
  return {
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    },
  };
}

function extractAssistantText(responseBody: unknown): string {
  const message = extractFirstChoiceMessage(responseBody);
  if (typeof message.content !== 'string' || !message.content.trim()) {
    throw new OpenAICompatibleError('模型响应不包含非空文本内容');
  }
  return message.content.trim();
}

function extractToolCallingCompletion(responseBody: unknown): ToolCallingCompletion {
  const message = extractFirstChoiceMessage(responseBody);
  const content = typeof message.content === 'string' ? message.content.trim() : '';
  if (message.tool_calls === undefined) {
    if (!content) {
      throw new OpenAICompatibleError('Model response does not contain text or tool calls.');
    }
    return { content, toolCalls: [] };
  }
  return {
    content,
    toolCalls: requireArray(message.tool_calls, 'Model tool calls are invalid.').map(
      extractToolCall,
    ),
  };
}

function extractFirstChoiceMessage(responseBody: unknown): Record<string, unknown> {
  const body = requireRecord(responseBody);
  const choices = requireArray(body.choices, '模型响应缺少 choices');
  const firstChoice = choices.at(0);
  if (firstChoice === undefined) {
    throw new OpenAICompatibleError('模型响应缺少 choices');
  }
  return requireRecord(requireRecord(firstChoice).message);
}

function extractToolCall(value: unknown): ToolCall {
  const toolCall = requireRecord(value);
  const functionCall = requireRecord(toolCall.function);
  if (
    typeof toolCall.id !== 'string' ||
    !toolCall.id.trim() ||
    toolCall.type !== 'function' ||
    typeof functionCall.name !== 'string' ||
    !functionCall.name.trim() ||
    typeof functionCall.arguments !== 'string'
  ) {
    throw new OpenAICompatibleError('Model tool call has an invalid format.');
  }
  return { id: toolCall.id, name: functionCall.name, arguments: functionCall.arguments };
}

function validateConfig(config: OpenAICompatibleConfig): ValidatedConfig {
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error('请求超时必须大于 0');
  }
  if (config.includeStreamUsage !== undefined && typeof config.includeStreamUsage !== 'boolean') {
    throw new TypeError('includeStreamUsage 必须是布尔值');
  }

  return {
    apiKey: normalizeRequiredText(config.apiKey, 'OPENAI_API_KEY 不能为空'),
    model: normalizeRequiredText(config.model, '模型名称不能为空'),
    baseUrl: normalizeRequiredText(config.baseUrl ?? DEFAULT_BASE_URL, '模型服务地址不能为空'),
    timeoutMs,
    includeStreamUsage: config.includeStreamUsage ?? true,
  };
}

function normalizeRequiredText(value: unknown, errorMessage: string): string {
  if (typeof value !== 'string') {
    throw new TypeError(errorMessage);
  }
  const normalizedValue = value.trim();
  if (!normalizedValue) {
    throw new Error(errorMessage);
  }
  return normalizedValue;
}

function completionUrl(baseUrl: string): string {
  return `${baseUrl.replace(/\/+$/, '')}/chat/completions`;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new OpenAICompatibleError('模型服务返回了无效的 JSON 响应');
  }
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new OpenAICompatibleError('模型响应结构不符合 OpenAI 兼容格式');
  }
  return value;
}

function requireArray(value: unknown, errorMessage: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new OpenAICompatibleError(errorMessage);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nonNegativeInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}
