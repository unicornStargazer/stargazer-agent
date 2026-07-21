/**
 * 实现 OpenAI 兼容的非流式文本聊天客户端。
 *
 * 负责把 ChatMessage 转换为 /chat/completions 请求并校验纯文本响应；不管理会话历史、重试、
 * 流式响应或工具调用。允许依赖 Node.js 原生 fetch 和 chat 消息类型。
 */

import type { ChatMessage, ChatModel } from '../chat/index.js';

const DEFAULT_BASE_URL = 'https://api.openai.com/v1';
const DEFAULT_TIMEOUT_MS = 60_000;

export interface OpenAICompatibleConfig {
  readonly apiKey: string;
  readonly model: string;
  readonly baseUrl?: string | undefined;
  readonly timeoutMs?: number | undefined;
}

export type FetchImplementation = typeof fetch;

interface ValidatedConfig {
  readonly apiKey: string;
  readonly model: string;
  readonly baseUrl: string;
  readonly timeoutMs: number;
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

  /** 提交完整消息序列，并从首个 choice 中读取非空助手文本。 */
  async complete(messages: readonly ChatMessage[]): Promise<string> {
    if (messages.length === 0) {
      throw new Error('至少需要一条消息才能调用模型');
    }
    const response = await this.requestCompletion(messages);
    if (!response.ok) {
      throw new OpenAICompatibleError(`模型服务返回 HTTP ${response.status}`);
    }
    return extractAssistantText(await parseJsonResponse(response));
  }

  private async requestCompletion(messages: readonly ChatMessage[]): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    try {
      return await this.fetchImplementation(completionUrl(this.config.baseUrl), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${this.config.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: this.config.model,
          messages: messages.map((message) => ({
            role: message.role,
            content: message.content,
          })),
        }),
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
}

function validateConfig(config: OpenAICompatibleConfig): ValidatedConfig {
  const apiKey = normalizeRequiredText(config.apiKey, 'OPENAI_API_KEY 不能为空');
  const model = normalizeRequiredText(config.model, '模型名称不能为空');
  const baseUrl = normalizeRequiredText(config.baseUrl ?? DEFAULT_BASE_URL, '模型服务地址不能为空');
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error('请求超时必须大于 0');
  }
  return { apiKey, model, baseUrl, timeoutMs };
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

function extractAssistantText(responseBody: unknown): string {
  const body = requireRecord(responseBody);
  const choices = requireArray(body.choices, '模型响应缺少 choices');
  const firstChoice = choices.at(0);
  if (firstChoice === undefined) {
    throw new OpenAICompatibleError('模型响应缺少 choices');
  }
  const message = requireRecord(requireRecord(firstChoice).message);
  const content = message.content;
  if (typeof content !== 'string' || !content.trim()) {
    throw new OpenAICompatibleError('模型响应不包含非空文本内容');
  }
  return content.trim();
}

function requireRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new OpenAICompatibleError('模型响应结构不符合 OpenAI 兼容格式');
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, errorMessage: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new OpenAICompatibleError(errorMessage);
  }
  return value;
}
