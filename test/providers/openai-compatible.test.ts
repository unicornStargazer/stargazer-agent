/** 验证 OpenAI 兼容客户端的请求映射、响应校验和错误脱敏。 */

import { describe, expect, it } from 'vitest';

import { createChatMessage } from '../../src/chat/models.js';
import type { ModelStreamEvent } from '../../src/chat/port.js';
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

  it('解析公开推理和 usage 统计事件', async () => {
    const responseBody = [
      'data: {"choices":[{"delta":{"reasoning_content":"先分析"}}]}\n\n',
      'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
      'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}\n\n',
      'data: [DONE]\n\n',
    ].join('');
    const fetchImplementation: typeof fetch = (_input, init) => {
      const requestBody = init?.body;
      if (typeof requestBody !== 'string') {
        throw new Error('请求体必须是 JSON 字符串');
      }
      expect(JSON.parse(requestBody)).toMatchObject({
        stream: true,
        stream_options: { include_usage: true },
      });
      return Promise.resolve(
        new Response(responseBody, {
          headers: { 'Content-Type': 'text/event-stream' },
        }),
      );
    };
    const model = new OpenAICompatibleChatModel(
      { apiKey: 'test-key', model: 'test-model' },
      fetchImplementation,
    );

    const events: ModelStreamEvent[] = [];
    for await (const event of model.stream([createChatMessage('user', '测试')])) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: 'reasoning', content: '先分析' },
      { type: 'content', content: '你好' },
      { type: 'usage', usage: { inputTokens: 5, outputTokens: 7, totalTokens: 12 } },
    ]);
  });

  it('maps registered tools and provider tool calls without exposing them as plain text', async () => {
    const fetchImplementation: typeof fetch = (_input, init) => {
      const requestBody = init?.body;
      if (typeof requestBody !== 'string') {
        throw new Error('Request body must be JSON text.');
      }
      expect(JSON.parse(requestBody)).toMatchObject({
        tools: [
          {
            type: 'function',
            function: {
              name: 'lookup_weather',
              parameters: { type: 'object' },
            },
          },
        ],
      });
      return Promise.resolve(
        Response.json({
          choices: [
            {
              message: {
                content: null,
                tool_calls: [
                  {
                    id: 'call-1',
                    type: 'function',
                    function: { name: 'lookup_weather', arguments: '{"city":"Shanghai"}' },
                  },
                ],
              },
            },
          ],
        }),
      );
    };
    const model = new OpenAICompatibleChatModel(
      { apiKey: 'test-key', model: 'test-model' },
      fetchImplementation,
    );

    await expect(
      model.completeWithTools(
        [createChatMessage('user', 'Weather?')],
        [
          {
            name: 'lookup_weather',
            description: 'Looks up a weather forecast.',
            parameters: { type: 'object' },
          },
        ],
      ),
    ).resolves.toEqual({
      content: '',
      toolCalls: [{ id: 'call-1', name: 'lookup_weather', arguments: '{"city":"Shanghai"}' }],
    });
  });
});
