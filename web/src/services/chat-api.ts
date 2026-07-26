import type { AgentProfile, AgentStatus, ApiChatMessage, ChatRequest } from '../types/chat';

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

export async function streamChatMessage(
  request: ChatRequest,
  onChunk: (content: string) => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
  } catch {
    throw new ChatApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查服务状态。');
  }
  if (!response.ok || response.body === null) {
    const body = await parseJson(response);
    const error = isRecord(body) ? (body as ApiErrorBody).error : undefined;
    throw new ChatApiError(
      response.status,
      typeof error?.code === 'string' ? error.code : 'REQUEST_FAILED',
      typeof error?.message === 'string' ? error.message : '请求失败',
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) return;
      buffer += decoder.decode(result.value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() ?? '';
      for (const event of events) {
        const type = event.match(/^event: (.+)$/m)?.[1];
        const data = event.match(/^data: (.+)$/m)?.[1];
        if (!type || !data) continue;
        const value = JSON.parse(data) as unknown;
        if (type === 'chunk' && isRecord(value) && typeof value.content === 'string')
          onChunk(value.content);
        if (type === 'error' && isRecord(value))
          throw new ChatApiError(
            502,
            typeof value.code === 'string' ? value.code : 'MODEL_UNAVAILABLE',
            typeof value.message === 'string' ? value.message : '模型暂时不可用',
          );
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function loadAgentProfiles(): Promise<readonly AgentProfile[]> {
  const body = await requestJson<unknown>('/api/profiles');
  if (!isRecord(body) || !Array.isArray(body.profiles) || !body.profiles.every(isAgentProfile)) {
    throw new ChatApiError(502, 'INVALID_RESPONSE', '服务端返回了无法识别的 Profile 列表');
  }
  return body.profiles;
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
    (value.conversationStorage === 'memory' || value.conversationStorage === 'sqlite') &&
    (value.defaultProfile === undefined || isAgentProfile(value.defaultProfile))
  );
}

function isAgentProfile(value: unknown): value is AgentProfile {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.model === 'string'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
