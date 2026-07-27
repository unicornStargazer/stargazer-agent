import { afterEach, describe, expect, it, vi } from 'vitest';

import { loadConversationHistory, streamChatMessage } from './chat-api';
import type { ChatApiError } from './chat-api';

const chatRequest = {
  sessionId: 'session-test',
  requestId: 'request-test',
  message: '你好',
  profileId: 'default',
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('chat API service', () => {
  it('parses SSE events split across network chunks', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          createStreamResponse([
            'event: chunk\ndata: {"cont',
            'ent":"第一段"}\n\nevent: reasoning\ndata: {"content":"先分析"}\n\nevent: usage\ndata: {"usage":{"inputTokens":5}}\n\nevent: chunk\ndata: {"content":"第二段"}\n\n',
            'event: done\ndata: {}\n\n',
          ]),
        ),
    );
    const chunks: string[] = [];
    const reasoning: string[] = [];
    const usages: unknown[] = [];

    await streamChatMessage(chatRequest, (content) => chunks.push(content), {
      onReasoning: (content) => reasoning.push(content),
      onUsage: (usage) => usages.push(usage),
    });

    expect(chunks).toEqual(['第一段', '第二段']);
    expect(reasoning).toEqual(['先分析']);
    expect(usages).toEqual([{ inputTokens: 5 }]);
  });

  it('rejects malformed SSE data with a stable response error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(createStreamResponse(['event: chunk\ndata: {invalid}\n\n'])),
    );

    await expect(streamChatMessage(chatRequest, () => undefined)).rejects.toMatchObject({
      code: 'INVALID_RESPONSE',
    } satisfies Partial<ChatApiError>);
  });

  it('validates conversation history responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            messages: [
              { role: 'user', content: '问题' },
              { role: 'assistant', content: '回答' },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    await expect(loadConversationHistory('session-test')).resolves.toEqual([
      { role: 'user', content: '问题' },
      { role: 'assistant', content: '回答' },
    ]);
  });
});

function createStreamResponse(chunks: readonly string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
        controller.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
}
