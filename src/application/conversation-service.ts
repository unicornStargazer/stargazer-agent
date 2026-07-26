/**
 * 统一协调同会话的串行、请求幂等和普通/流式聊天生命周期。
 * HTTP 层只负责把请求转换为命令，并不持有会话状态。
 */

import type { ChatMessage } from '../chat/index.js';

export interface ConversationCommand {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string | undefined;
}

export interface ConversationAgent {
  chat(sessionId: string, profileId: string | undefined, message: string): Promise<ChatMessage>;
  chatStream(
    sessionId: string,
    profileId: string | undefined,
    message: string,
  ): AsyncIterable<string>;
  clearHistory(sessionId: string): Promise<void>;
}

export class RequestConflictError extends Error {
  constructor() {
    super('requestId 已用于其他消息');
    this.name = 'RequestConflictError';
  }
}

export class SessionBusyError extends Error {
  constructor() {
    super('会话正在生成回复，暂时无法删除');
    this.name = 'SessionBusyError';
  }
}

interface CompletedRequest {
  readonly message: string;
  readonly response: ChatMessage;
}
interface InFlightRequest {
  readonly message: string;
  readonly response: Promise<ChatMessage>;
}

export class ConversationService {
  private readonly completedRequests = new Map<string, CompletedRequest>();
  private readonly inFlightRequests = new Map<string, InFlightRequest>();
  private readonly sessionQueues = new Map<string, Promise<void>>();

  constructor(
    private readonly agent: ConversationAgent,
    private readonly maximumCompletedRequests = 500,
  ) {}

/**
 * 异步处理聊天命令的方法
 * @param command 包含会话命令信息的对象，包括会话ID、用户档案ID和消息内容
 * @returns 返回一个Promise，解析为ChatMessage类型的聊天消息
 */
  async chat(command: ConversationCommand): Promise<ChatMessage> {
    // 获取或创建一个会话，如果不存在则使用提供的回调函数创建
    // 回调函数中执行排队操作，确保会话处理的顺序性
    return this.getOrCreate(command, () =>
      // 在指定会话ID上执行排队操作
      this.runQueued(command.sessionId, () =>
        // 调用智能体进行实际聊天处理，传入会话ID、用户档案ID和消息内容
        this.agent.chat(command.sessionId, command.profileId, command.message),
      ),
    );
  }

/**
 * 流式处理对话命令，支持并发请求处理和缓存机制
 * @param command 对话命令对象，包含会话ID、配置ID和消息内容
 * @param onChunk 处理每个数据块的回调函数
 * @returns Promise<void>
 */
  async stream(command: ConversationCommand, onChunk: (chunk: string) => void): Promise<void> {
    // 生成请求的唯一标识
    const requestKey = this.requestKey(command);
    // 检查是否已有已完成的请求
    const completed = this.completedRequests.get(requestKey);
    if (completed !== undefined) {
      // 确保消息内容一致，防止请求冲突
      this.requireSameMessage(completed.message, command.message);
      // 直接返回已完成的响应内容
      onChunk(completed.response.content);
      return;
    }
    // 检查是否有正在处理的请求
    const inFlight = this.inFlightRequests.get(requestKey);
    if (inFlight !== undefined) {
      // 确保消息内容一致，防止请求冲突
      this.requireSameMessage(inFlight.message, command.message);
      // 返回正在处理的请求的响应内容
      onChunk((await inFlight.response).content);
      return;
    }
    // 创建新的请求响应
    const response = this.runQueued(command.sessionId, async () => {
      let content = '';
      // 流式获取AI助手的响应
      for await (const chunk of this.agent.chatStream(
        command.sessionId,
        command.profileId,
        command.message,
      )) {
        content += chunk;
        onChunk(chunk);
      }
      return { role: 'assistant' as const, content };
    });
    // 将请求添加到处理中的请求集合
    this.inFlightRequests.set(requestKey, { message: command.message, response });
    try {
      // 记录完成的请求
      this.remember(requestKey, command.message, await response);
    } finally {
      // 无论成功失败，都从处理中的请求集合中移除
      this.inFlightRequests.delete(requestKey);
    }
  }

  async clear(sessionId: string): Promise<void> {
    if ([...this.inFlightRequests.keys()].some((key) => key.startsWith(`${sessionId}\u0000`)))
      throw new SessionBusyError();
    await this.agent.clearHistory(sessionId);
    for (const key of this.completedRequests.keys())
      if (key.startsWith(`${sessionId}\u0000`)) this.completedRequests.delete(key);
  }

  private async getOrCreate(
    command: ConversationCommand,
    create: () => Promise<ChatMessage>,
  ): Promise<ChatMessage> {
    const requestKey = this.requestKey(command);
    const completed = this.completedRequests.get(requestKey);
    if (completed !== undefined) {
      this.requireSameMessage(completed.message, command.message);
      return completed.response;
    }
    const inFlight = this.inFlightRequests.get(requestKey);
    if (inFlight !== undefined) {
      this.requireSameMessage(inFlight.message, command.message);
      return inFlight.response;
    }
    const response = create();
    this.inFlightRequests.set(requestKey, { message: command.message, response });
    try {
      const result = await response;
      this.remember(requestKey, command.message, result);
      return result;
    } finally {
      this.inFlightRequests.delete(requestKey);
    }
  }

  private async runQueued<T>(sessionId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.sessionQueues.get(sessionId) ?? Promise.resolve();
    let release: (() => void) | undefined;
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.sessionQueues.set(sessionId, current);
    await previous;
    try {
      return await operation();
    } finally {
      release?.();
      if (this.sessionQueues.get(sessionId) === current) this.sessionQueues.delete(sessionId);
    }
  }

  private requestKey(command: ConversationCommand): string {
    return `${command.sessionId}\u0000${command.requestId}`;
  }
  private requireSameMessage(current: string, received: string): void {
    if (current !== received) throw new RequestConflictError();
  }
  private remember(key: string, message: string, response: ChatMessage): void {
    this.completedRequests.set(key, { message, response });
    if (this.completedRequests.size > this.maximumCompletedRequests) {
      const oldest = this.completedRequests.keys().next().value;
      if (oldest !== undefined) this.completedRequests.delete(oldest);
    }
  }
}
