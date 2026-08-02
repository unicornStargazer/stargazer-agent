/** 应用服务：协调请求幂等、同会话串行和 Agent 调用，不包含 HTTP 或持久化实现细节。 */

import type { ChatMessage, ModelStreamEvent } from '../chat/index.js';

export interface ConversationCommand {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string | undefined;
}

export interface ConversationAgent {
  /** 返回完整回答；实现不得自行处理请求幂等或同会话并发。 */
  chat(sessionId: string, profileId: string | undefined, message: string): Promise<ChatMessage>;
  /** 按产生顺序输出模型事件；流结束前不得遗漏已经输出的内容。 */
  chatStream(
    sessionId: string,
    profileId: string | undefined,
    message: string,
  ): AsyncIterable<ModelStreamEvent>;
  clearHistory(sessionId: string): Promise<void>;
}

export class RequestConflictError extends Error {
  constructor() {
    super('requestId 已用于其他消息。');
    this.name = 'RequestConflictError';
  }
}

export class SessionBusyError extends Error {
  constructor() {
    super('会话正在生成回复，暂时无法删除。');
    this.name = 'SessionBusyError';
  }
}

interface RequestRecord {
  readonly message: string;
  readonly response: ChatMessage;
}

interface InFlightRequest {
  readonly message: string;
  readonly response: Promise<ChatMessage>;
}

export class ConversationService {
  private readonly completedRequests = new Map<string, RequestRecord>();
  private readonly inFlightRequests = new Map<string, InFlightRequest>();
  private readonly sessionQueues = new Map<string, Promise<void>>();

  constructor(
    private readonly agent: ConversationAgent,
    private readonly maximumCompletedRequests = 500,
  ) {}

  async chat(command: ConversationCommand): Promise<ChatMessage> {
    return this.getOrCreate(command, () =>
      this.runQueued(command.sessionId, () =>
        this.agent.chat(command.sessionId, command.profileId, command.message),
      ),
    );
  }

  async stream(
    command: ConversationCommand,
    onEvent: (event: ModelStreamEvent) => void,
  ): Promise<void> {
    const requestKey = this.requestKey(command);
    const completed = this.completedRequests.get(requestKey);
    if (completed !== undefined) {
      this.requireSameMessage(completed.message, command.message);
      onEvent({ type: 'content', content: completed.response.content });
      return;
    }

    const inFlight = this.inFlightRequests.get(requestKey);
    if (inFlight !== undefined) {
      this.requireSameMessage(inFlight.message, command.message);
      onEvent({ type: 'content', content: (await inFlight.response).content });
      return;
    }

    const response = this.runQueued(command.sessionId, () => this.streamResponse(command, onEvent));
    this.inFlightRequests.set(requestKey, { message: command.message, response });
    try {
      this.remember(requestKey, command.message, await response);
    } finally {
      this.inFlightRequests.delete(requestKey);
    }
  }

  async clear(sessionId: string): Promise<void> {
    if (this.hasInFlightRequest(sessionId)) {
      throw new SessionBusyError();
    }
    await this.agent.clearHistory(sessionId);
    this.removeCompletedRequests(sessionId);
  }

  /**
   * 流式输出时在服务层汇总文本，确保相同 requestId 重放时仍能得到完整回答。
   * reasoning、usage 等事件只透传给当前连接，不纳入会话消息。
   */
  private async streamResponse(
    command: ConversationCommand,
    onEvent: (event: ModelStreamEvent) => void,
  ): Promise<ChatMessage> {
    let content = '';
    for await (const event of this.agent.chatStream(
      command.sessionId,
      command.profileId,
      command.message,
    )) {
      if (event.type === 'content') {
        content += event.content;
      }
      onEvent(event);
    }
    return { role: 'assistant', content };
  }

  private async getOrCreate(
    command: ConversationCommand,
    createResponse: () => Promise<ChatMessage>,
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

    const response = createResponse();
    this.inFlightRequests.set(requestKey, { message: command.message, response });
    try {
      const completedResponse = await response;
      this.remember(requestKey, command.message, completedResponse);
      return completedResponse;
    } finally {
      this.inFlightRequests.delete(requestKey);
    }
  }

  /**
   * 将同一 session 的写入和模型调用串行化，避免两个请求读取相同历史后乱序持久化。
   * 不同会话仍可并行执行，因此锁的粒度限定为 sessionId。
   */
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
      if (this.sessionQueues.get(sessionId) === current) {
        this.sessionQueues.delete(sessionId);
      }
    }
  }

  private remember(requestKey: string, message: string, response: ChatMessage): void {
    this.completedRequests.set(requestKey, { message, response });
    if (this.completedRequests.size > this.maximumCompletedRequests) {
      const oldestRequestKey = this.completedRequests.keys().next().value;
      if (oldestRequestKey !== undefined) {
        this.completedRequests.delete(oldestRequestKey);
      }
    }
  }

  private hasInFlightRequest(sessionId: string): boolean {
    return [...this.inFlightRequests.keys()].some((key) => key.startsWith(`${sessionId}\u0000`));
  }

  private removeCompletedRequests(sessionId: string): void {
    for (const requestKey of this.completedRequests.keys()) {
      if (requestKey.startsWith(`${sessionId}\u0000`)) {
        this.completedRequests.delete(requestKey);
      }
    }
  }

  private requestKey(command: ConversationCommand): string {
    return `${command.sessionId}\u0000${command.requestId}`;
  }

  private requireSameMessage(expected: string, received: string): void {
    if (expected !== received) {
      throw new RequestConflictError();
    }
  }
}
