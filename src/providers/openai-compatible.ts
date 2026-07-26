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

  /**
   * 异步完成对话的方法
   * @param messages - 只读的聊天消息数组，包含对话历史
   * @returns 返回助手生成的回复文本
   * @throws 当消息数组为空或模型服务返回错误时抛出异常
   */
  async complete(messages: readonly ChatMessage[]): Promise<string> {
    // 检查消息数组是否为空，为空则抛出错误
    if (messages.length === 0) {
      throw new Error('至少需要一条消息才能调用模型');
    }
    // 发送请求到模型服务并获取响应
    const response = await this.requestCompletion(messages);
    // 检查响应是否成功，不成功则抛出错误
    if (!response.ok) {
      throw new OpenAICompatibleError(`模型服务返回 HTTP ${response.status}`);
    }
    // 解析响应并提取助手文本后返回
    return extractAssistantText(await parseJsonResponse(response));
  }

  async *stream(messages: readonly ChatMessage[]): AsyncGenerator<string> {
    if (messages.length === 0) throw new Error('至少需要一条消息才能调用模型');
    const response = await this.requestCompletion(messages, true);
    if (!response.ok || response.body === null)
      throw new OpenAICompatibleError(`模型服务返回 HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        buffer += decoder.decode(result.value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const data = line.slice(5).trim();
          if (data === '[DONE]') return;
          const chunk = streamText(data);
          if (chunk) yield chunk;
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * 请求模型完成对话的私有异步方法
   * @param messages - 聊天消息的只读数组，包含对话历史
   * @returns 返回一个Promise，解析为Response对象
   * @throws 当请求超时或连接失败时抛出OpenAICompatibleError
   */
  private async requestCompletion(
    messages: readonly ChatMessage[],
    stream = false,
  ): Promise<Response> {
    // 创建一个AbortController实例用于控制请求超时
    const controller = new AbortController();
    // 设置定时器，在配置的超时时间后中止请求
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    try {
      // 使用fetchImplementation发送POST请求到模型服务
      return await this.fetchImplementation(completionUrl(this.config.baseUrl), {
        method: 'POST', // 请求方法为POST
        headers: {
          // 设置请求头
          Authorization: `Bearer ${this.config.apiKey}`, // 认证token
          'Content-Type': 'application/json', // 内容类型为JSON
        },
        // 请求体，包含模型名称和消息列表
        body: JSON.stringify({
          model: this.config.model, // 使用的模型名称
          messages: messages.map((message) => ({
            // 转换消息格式
            role: message.role, // 消息角色
            content: message.content, // 消息内容
          })),
          ...(stream ? { stream: true } : {}),
        }),
        signal: controller.signal, // 绑定中止信号
      });
    } catch {
      // 检查是否是请求被中止（超时）
      if (controller.signal.aborted) {
        throw new OpenAICompatibleError('模型服务请求超时');
      }
      // 其他连接错误
      throw new OpenAICompatibleError('无法连接模型服务');
    } finally {
      // 确保清除定时器，防止内存泄漏
      clearTimeout(timeoutId);
    }
  }
}

function streamText(value: string): string | undefined {
  try {
    const body = requireRecord(JSON.parse(value) as unknown);
    const choices = requireArray(body.choices, '模型流响应缺少 choices');
    const delta = requireRecord(requireRecord(choices[0]).delta);
    return typeof delta.content === 'string' ? delta.content : undefined;
  } catch (error) {
    if (error instanceof OpenAICompatibleError) throw error;
    throw new OpenAICompatibleError('模型流响应不是有效 JSON');
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
