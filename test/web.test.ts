import type { AddressInfo } from 'node:net';
import { resolve } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FastifyInstance } from 'fastify';

import type { ChatMessage, ChatModel } from '../src/chat/index.js';
import { ChatAgent, ConversationStoreError, InMemoryConversationStore } from '../src/chat/index.js';
import { ProfileAgent } from '../src/profiles/index.js';
import { FakeChatModel } from '../src/providers/index.js';
import { createHttpApp } from '../src/http/app.js';

const openServers: FastifyInstance[] = [];

afterEach(async () => {
  await Promise.all(openServers.splice(0).map((server) => server.close()));
});

describe('Web server', () => {
  it('serves the chat workspace and status without exposing credentials', async () => {
    const origin = await startServer(new ChatAgent({ model: new FakeChatModel([]) }));

    const pageResponse = await fetch(origin);
    const statusResponse = await fetch(`${origin}/api/status`);

    expect(pageResponse.status).toBe(200);
    expect(pageResponse.headers.get('content-security-policy')).toContain("default-src 'self'");
    expect(await pageResponse.text()).toContain('Stargazer');
    await expect(statusResponse.json()).resolves.toEqual({
      ready: true,
      model: 'test-model',
      conversationStorage: 'memory',
    });
  });

  it('rejects static paths outside the configured public directory', async () => {
    const origin = await startServer(new ChatAgent({ model: new FakeChatModel([]) }));

    const response = await fetch(`${origin}/%2e%2e%2fpackage.json`);

    expect(response.status).toBe(404);
  });

  it('completes chat requests, keeps history, and deduplicates retries', async () => {
    const model = new FakeChatModel(['第一条回复']);
    const origin = await startServer(new ChatAgent({ model }));
    const request = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 'session-1', requestId: 'request-1', message: '你好' }),
    };

    const firstResponse = await fetch(`${origin}/api/chat`, request);
    const retryResponse = await fetch(`${origin}/api/chat`, request);
    const historyResponse = await fetch(`${origin}/api/history?sessionId=session-1`);

    await expect(firstResponse.json()).resolves.toEqual({
      message: { role: 'assistant', content: '第一条回复' },
    });
    await expect(retryResponse.json()).resolves.toEqual({
      message: { role: 'assistant', content: '第一条回复' },
    });
    await expect(historyResponse.json()).resolves.toEqual({
      messages: [
        { role: 'user', content: '你好' },
        { role: 'assistant', content: '第一条回复' },
      ],
    });
    expect(model.requests).toHaveLength(1);
  });

  it('streams complete text and persists it only after the stream finishes', async () => {
    const store = new InMemoryConversationStore();
    const profileAgent = new ProfileAgent({
      profiles: [{ id: 'default', name: '默认助手', model: 'test-model' }],
      defaultProfileId: 'default',
      conversationStore: store,
      createModel: () => new FakeChatModel(['流式回复']),
    });
    const server = createHttpApp({
      agent: new ChatAgent({ model: new FakeChatModel([]) }),
      profileAgent,
      publicDirectory: resolve(process.cwd(), 'web'),
    });
    openServers.push(server);
    await server.listen({ port: 0, host: '127.0.0.1' });
    const address = server.server.address() as AddressInfo;

    const response = await fetch(
      `http://127.0.0.1:${String(address.port)}/api/chat/stream`,
      createChatRequest('你好', 'request-1'),
    );

    expect(response.headers.get('content-type')).toContain('text/event-stream');
    await expect(response.text()).resolves.toContain('"content":"流式回复"');
    await expect(store.messages('session-1')).resolves.toEqual([
      { role: 'user', content: '你好' },
      { role: 'assistant', content: '流式回复' },
    ]);
  });

  it('rejects invalid input with a stable client error', async () => {
    const origin = await startServer(new ChatAgent({ model: new FakeChatModel([]) }));

    const response = await fetch(`${origin}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 'session-1', requestId: 'request-1', message: ' ' }),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: { code: 'INVALID_REQUEST', message: 'message 不能为空。' },
    });
  });

  it('rejects content types that only share the JSON prefix', async () => {
    const origin = await startServer(new ChatAgent({ model: new FakeChatModel([]) }));

    const response = await fetch(`${origin}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/jsonp' },
      body: JSON.stringify({ sessionId: 'session-1', requestId: 'request-1', message: '你好' }),
    });

    expect(response.status).toBe(415);
  });

  it('rejects a reused request id with a different message', async () => {
    const model = new FakeChatModel(['第一条回复']);
    const origin = await startServer(new ChatAgent({ model }));
    const firstRequest = createChatRequest('第一条消息', 'request-1');

    await fetch(`${origin}/api/chat`, firstRequest);
    const conflictResponse = await fetch(
      `${origin}/api/chat`,
      createChatRequest('被错误复用的消息', 'request-1'),
    );

    expect(conflictResponse.status).toBe(409);
    await expect(conflictResponse.json()).resolves.toEqual({
      error: { code: 'REQUEST_CONFLICT', message: 'requestId 已用于其他消息。' },
    });
    expect(model.requests).toHaveLength(1);
  });

  it('serializes different requests in the same session', async () => {
    const model = new ControlledChatModel();
    const origin = await startServer(new ChatAgent({ model }));

    const firstResponse = fetch(`${origin}/api/chat`, createChatRequest('第一条消息', 'request-1'));
    await vi.waitFor(() => expect(model.requests).toHaveLength(1));
    const secondResponse = fetch(
      `${origin}/api/chat`,
      createChatRequest('第二条消息', 'request-2'),
    );
    await new Promise((resolveImmediate) => setImmediate(resolveImmediate));
    expect(model.requests).toHaveLength(1);

    model.resolveNext('第一条回复');
    expect((await firstResponse).status).toBe(200);
    await vi.waitFor(() => expect(model.requests).toHaveLength(2));
    expect(model.requests.at(1)).toEqual([
      { role: 'user', content: '第一条消息' },
      { role: 'assistant', content: '第一条回复' },
      { role: 'user', content: '第二条消息' },
    ]);
    model.resolveNext('第二条回复');
    expect((await secondResponse).status).toBe(200);
  });

  it('maps model failures without leaking the internal error', async () => {
    const failingAgent = {
      history: () => Promise.resolve([]),
      clearHistory: () => Promise.resolve(),
      chat: () => Promise.reject(new Error('secret upstream response')),
    };
    const origin = await startServer(failingAgent);

    const response = await fetch(`${origin}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: 'session-1', requestId: 'request-1', message: '你好' }),
    });

    expect(response.status).toBe(502);
    expect(await response.text()).toBe(
      JSON.stringify({
        error: { code: 'MODEL_UNAVAILABLE', message: '模型暂时不可用，请稍后重试。' },
      }),
    );
  });

  it('reports conversation storage failures without pretending history is empty', async () => {
    const origin = await startServer({
      history: () => Promise.resolve([]),
      clearHistory: () => Promise.resolve(),
      chat: () => Promise.reject(new ConversationStoreError('database disk I/O error')),
    });

    const response = await fetch(
      `${origin}/api/chat`,
      createChatRequest('需要保存的消息', 'request-1'),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'CONVERSATION_STORAGE_UNAVAILABLE',
        message: '会话存储暂时不可用，请稍后重试。',
      },
    });
  });

  it('returns a storage error when reading history fails', async () => {
    const origin = await startServer({
      history: () => Promise.reject(new ConversationStoreError('database read error')),
      clearHistory: () => Promise.resolve(),
      chat: () => Promise.resolve({ role: 'assistant', content: '不应调用' }),
    });

    const response = await fetch(`${origin}/api/history?sessionId=session-1`);

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'CONVERSATION_STORAGE_UNAVAILABLE',
        message: '会话存储暂时不可用，请稍后重试。',
      },
    });
  });

  it('maps a shared in-flight model failure consistently for every caller', async () => {
    const chat = vi.fn(
      () =>
        new Promise<ChatMessage>((_resolveChat, rejectChat) => {
          setTimeout(() => rejectChat(new Error('secret shared upstream response')), 50);
        }),
    );
    const origin = await startServer({
      history: () => Promise.resolve([]),
      clearHistory: () => Promise.resolve(),
      chat,
    });
    const request = createChatRequest('并发消息', 'shared-request');

    const responses = await Promise.all([
      fetch(`${origin}/api/chat`, request),
      fetch(`${origin}/api/chat`, request),
    ]);

    expect(responses.map((response) => response.status)).toEqual([502, 502]);
    await expect(Promise.all(responses.map((response) => response.json()))).resolves.toEqual([
      { error: { code: 'MODEL_UNAVAILABLE', message: '模型暂时不可用，请稍后重试。' } },
      { error: { code: 'MODEL_UNAVAILABLE', message: '模型暂时不可用，请稍后重试。' } },
    ]);
    expect(chat).toHaveBeenCalledOnce();
  });

  it('deletes server history and its completed request cache', async () => {
    const model = new FakeChatModel(['第一条回复', '删除后的回复']);
    const origin = await startServer(new ChatAgent({ model }));
    const request = createChatRequest('第一条消息', 'request-1');
    await fetch(`${origin}/api/chat`, request);

    const deleteResponse = await fetch(`${origin}/api/history?sessionId=session-1`, {
      method: 'DELETE',
    });
    const historyResponse = await fetch(`${origin}/api/history?sessionId=session-1`);
    const repeatedResponse = await fetch(`${origin}/api/chat`, request);

    expect(deleteResponse.status).toBe(200);
    await expect(historyResponse.json()).resolves.toEqual({ messages: [] });
    await expect(repeatedResponse.json()).resolves.toEqual({
      message: { role: 'assistant', content: '删除后的回复' },
    });
    expect(model.requests).toHaveLength(2);
  });
});

async function startServer(agent: Parameters<typeof createHttpApp>[0]['agent']): Promise<string> {
  const server = createHttpApp({
    agent,
    modelName: 'test-model',
    publicDirectory: resolve(process.cwd(), 'web'),
  });
  openServers.push(server);
  await server.listen({ port: 0, host: '127.0.0.1' });
  const address = server.server.address() as AddressInfo;
  return `http://127.0.0.1:${String(address.port)}`;
}

function createChatRequest(message: string, requestId: string): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId: 'session-1', requestId, message }),
  };
}

class ControlledChatModel implements ChatModel {
  readonly requests: ChatMessage[][] = [];
  private readonly responseResolvers: Array<(response: string) => void> = [];

  complete(messages: readonly ChatMessage[]): Promise<string> {
    this.requests.push([...messages]);
    return new Promise((resolveResponse) => this.responseResolvers.push(resolveResponse));
  }

  resolveNext(response: string): void {
    const resolveResponse = this.responseResolvers.shift();
    if (resolveResponse === undefined) {
      throw new Error('没有等待中的模型请求');
    }
    resolveResponse(response);
  }
}
