/** 验证 OpenAI 兼容客户端的请求映射、响应校验和错误脱敏。 */

import { describe, expect, it } from 'vitest';

import { createChatMessage } from '../../src/chat/models.js';
import {
  OpenAICompatibleChatModel,
  OpenAICompatibleError,
} from '../../src/providers/openai-compatible.js';

describe('OpenAICompatibleChatModel', () => {
  it('按 OpenAI 兼容格式发送有序文本消息', async () => {
    const fetchImplementation: typeof fetch = (input, init) => {
      expect(input).toBe('https://models.example.test/v1/chat/completions');
      expect(init?.method).toBe('POST');
      expect(new Headers(init?.headers).get('authorization')).toBe('Bearer test-key');
      const requestBody = init?.body;
      if (typeof requestBody !== 'string') {
        throw new Error('请求体必须是 JSON 字符串');
      }
      expect(JSON.parse(requestBody)).toEqual({
        model: 'test-model',
        messages: [
          { role: 'system', content: '回答要简洁' },
          { role: 'user', content: '你好' },
        ],
      });
      return Promise.resolve(Response.json({ choices: [{ message: { content: '你好!' } }] }));
    };
    const model = new OpenAICompatibleChatModel(
      {
        apiKey: 'test-key',
        model: 'test-model',
        baseUrl: 'https://models.example.test/v1/',
      },
      fetchImplementation,
    );

    const response = await model.complete([
      createChatMessage('system', '回答要简洁'),
      createChatMessage('user', '你好'),
    ]);

    expect(response).toBe('你好!');
  });

  it('HTTP 错误不回显服务端可能包含密钥的响应正文', async () => {
    const fetchImplementation: typeof fetch = () =>
      Promise.resolve(new Response('api-key=test-key', { status: 401 }));
    const model = new OpenAICompatibleChatModel(
      { apiKey: 'test-key', model: 'test-model' },
      fetchImplementation,
    );

    await expect(model.complete([createChatMessage('user', '你好')])).rejects.toEqual(
      new OpenAICompatibleError('模型服务返回 HTTP 401'),
    );
  });

  it('忽略文本分片后的 usage 统计事件', async () => {
    const responseBody = [
      'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
      'data: {"choices":[],"usage":{"total_tokens":12}}\n\n',
      'data: [DONE]\n\n',
    ].join('');
    const fetchImplementation: typeof fetch = () =>
      Promise.resolve(
        new Response(responseBody, {
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      );
    const model = new OpenAICompatibleChatModel(
      { apiKey: 'test-key', model: 'test-model' },
      fetchImplementation,
    );

    const chunks: string[] = [];
    for await (const chunk of model.stream([createChatMessage('user', '测试')])) {
      chunks.push(chunk);
    }

    expect(chunks).toEqual(['你好']);
  });
});
