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

  /**
   * 异步生成器函数，用于流式处理聊天消息并返回响应文本
   * @param messages - 只读的聊天消息数组，至少需要包含一条消息
   * @returns AsyncGenerator<string> - 返回一个异步生成器，每次yield一个文本块
   * @throws 当消息数组为空时抛出错误
   * @throws 当模型服务返回非200状态码时抛出OpenAICompatibleError
   */
  async *stream(messages: readonly ChatMessage[]): AsyncGenerator<string> {
    // 检查消息数组是否为空，为空则抛出错误
    if (messages.length === 0) throw new Error('至少需要一条消息才能调用模型');
    // 发送请求获取响应，第二个参数true表示启用流式处理
    const response = await this.requestCompletion(messages, true);
    // 检查响应是否有效，无效则抛出错误
    if (!response.ok || response.body === null)
      throw new OpenAICompatibleError(`模型服务返回 HTTP ${response.status}`);
    // 获取响应流的读取器和文本解码器
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ''; // 用于存储不完整的行数据
    try {
      // 无限循环，直到流结束
      while (true) {
        // 读取流数据
        const result = await reader.read();
        if (result.done) break; // 如果流结束，退出循环
        // 解码读取到的数据并追加到缓冲区
        buffer += decoder.decode(result.value, { stream: true });
        // 按行分割缓冲区内容
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? ''; // 保留最后一行（可能不完整）
        // 处理每一行数据
        for (const line of lines) {
          // 跳过非数据行
          if (!line.startsWith('data:')) continue;
          // 提取数据部分并去除前后空格
          const data = line.slice(5).trim();
          // 遇到结束标记则结束生成器
          if (data === '[DONE]') return;
          // 处理数据块并yield结果
          const chunk = streamText(data);
          if (chunk) yield chunk;
        }
      }
    } finally {
      // 确保释放读取器锁
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

/**
 * 流式文本处理函数，用于解析和提取流式响应中的文本内容
 * @param value - JSON格式的字符串，包含流式响应数据
 * @returns 返回解析后的文本内容，如果解析失败或不符合预期则返回undefined
 */
function streamText(value: string): string | undefined {
  try {
    // 将输入的JSON字符串解析为对象，并确保其符合Record类型
    const body = requireRecord(JSON.parse(value) as unknown);
    // 确保body.choices存在且为数组，如果不存在则抛出错误
    const choices = requireArray(body.choices, '模型流响应缺少 choices');
    // 获取choices数组的第一个元素
    const firstChoice = choices.at(0);
    // 部分兼容服务会在结尾追加 usage 统计事件，choices 为空且不表示生成失败。
    if (firstChoice === undefined) {
      return undefined;
    }
    const choice = requireRecord(firstChoice);
    if (typeof choice.delta !== 'object' || choice.delta === null || Array.isArray(choice.delta)) {
      return undefined;
    }
    const delta = requireRecord(choice.delta);
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
