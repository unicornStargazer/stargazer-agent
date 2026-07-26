import type { AgentStatus, ApiChatMessage, ChatRequest } from '../types/chat';

interface ApiErrorBody {
  readonly error?: {
    readonly code?: unknown;
    readonly message?: unknown;
  };
}

interface ChatResponseBody {
  readonly message?: unknown;
}

export class ChatApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ChatApiError';
  }
}

export async function loadAgentStatus(): Promise<AgentStatus> {
  const body = await requestJson<unknown>('/api/status');
  if (!isAgentStatus(body)) {
    throw new ChatApiError(502, 'INVALID_RESPONSE', '服务返回了无法识别的状态。');
  }
  return body;
}

export async function sendChatMessage(request: ChatRequest): Promise<ApiChatMessage> {
  const body = await requestJson<ChatResponseBody>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!isAssistantMessage(body.message)) {
    throw new ChatApiError(502, 'INVALID_RESPONSE', '服务返回了无法识别的消息。');
  }
  return body.message;
}

export async function deleteServerConversation(sessionId: string): Promise<void> {
  await requestJson(`/api/history?sessionId=${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ChatApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查服务状态。');
  }

  const body = await parseJson(response);
  if (!response.ok) {
    const errorBody = isRecord(body) ? (body as ApiErrorBody) : undefined;
    const message = errorBody?.error?.message;
    const code = errorBody?.error?.code;
    throw new ChatApiError(
      response.status,
      typeof code === 'string' ? code : 'REQUEST_FAILED',
      typeof message === 'string' ? message : '请求失败，请稍后重试。',
    );
  }
  return body as T;
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new ChatApiError(response.status, 'INVALID_RESPONSE', '服务返回了无效响应。');
  }
}

function isAssistantMessage(value: unknown): value is ApiChatMessage {
  return (
    isRecord(value) &&
    value.role === 'assistant' &&
    typeof value.content === 'string' &&
    !!value.content
  );
}

function isAgentStatus(value: unknown): value is AgentStatus {
  return (
    isRecord(value) &&
    value.ready === true &&
    typeof value.model === 'string' &&
    value.conversationStorage === 'memory'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
