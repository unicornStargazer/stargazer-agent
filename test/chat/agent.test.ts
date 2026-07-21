/** 验证最小 ChatAgent 的会话编排和失败边界。 */

import { describe, expect, it } from 'vitest';

import { ChatAgent } from '../../src/chat/agent.js';
import { FakeChatModel } from '../../src/providers/fake-chat-model.js';

describe('ChatAgent', () => {
  it('每轮注入一次系统提示，并保存同一会话的前序消息', async () => {
    const model = new FakeChatModel(['第一轮回答', '第二轮回答']);
    const agent = new ChatAgent({ model, systemPrompt: '你是简洁的助手' });

    await agent.chat('demo', '你好');
    const secondResponse = await agent.chat('demo', '继续');

    expect(secondResponse.content).toBe('第二轮回答');
    expect(model.requests[1]).toEqual([
      { role: 'system', content: '你是简洁的助手' },
      { role: 'user', content: '你好' },
      { role: 'assistant', content: '第一轮回答' },
      { role: 'user', content: '继续' },
    ]);
    expect(agent.history('demo')).toEqual([
      { role: 'user', content: '你好' },
      { role: 'assistant', content: '第一轮回答' },
      { role: 'user', content: '继续' },
      { role: 'assistant', content: '第二轮回答' },
    ]);
  });

  it('模型返回空白文本时不写入部分会话轮次', async () => {
    const agent = new ChatAgent({ model: new FakeChatModel(['  ']) });

    await expect(agent.chat('demo', '需要回答的问题')).rejects.toThrow('消息内容不能为空');

    expect(agent.history('demo')).toEqual([]);
  });
});
