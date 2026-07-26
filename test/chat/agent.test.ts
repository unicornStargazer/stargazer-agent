/** 验证 ChatAgent 的消息编排、上下文窗口与存储失败边界。 */

import { describe, expect, it } from 'vitest';

import { ChatAgent } from '../../src/chat/agent.js';
import type { ConversationStore } from '../../src/chat/conversation-store.js';
import type { ChatMessage } from '../../src/chat/models.js';
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
    await expect(agent.history('demo')).resolves.toEqual([
      { role: 'user', content: '你好' },
      { role: 'assistant', content: '第一轮回答' },
      { role: 'user', content: '继续' },
      { role: 'assistant', content: '第二轮回答' },
    ]);
  });

  it('模型返回空白文本时不写入部分会话轮次', async () => {
    const agent = new ChatAgent({ model: new FakeChatModel(['  ']) });

    await expect(agent.chat('demo', '需要回答的问题')).rejects.toThrow('消息内容不能为空');

    await expect(agent.history('demo')).resolves.toEqual([]);
  });

  it('只将指定窗口内的最近历史发送给模型', async () => {
    const model = new FakeChatModel(['回答一', '回答二', '回答三']);
    const agent = new ChatAgent({ model, historyLimit: 2 });

    await agent.chat('demo', '问题一');
    await agent.chat('demo', '问题二');
    await agent.chat('demo', '问题三');

    expect(model.requests[2]).toEqual([
      { role: 'user', content: '问题二' },
      { role: 'assistant', content: '回答二' },
      { role: 'user', content: '问题三' },
    ]);
    await expect(agent.history('demo')).resolves.toHaveLength(6);
  });

  it('存储拒绝完整轮次时不尝试单独追加用户消息', async () => {
    const store = new RejectingConversationStore();
    const agent = new ChatAgent({
      model: new FakeChatModel(['模型回答']),
      conversationStore: store,
    });

    await expect(agent.chat('demo', '问题')).rejects.toThrow('存储故障');

    expect(store.appendAttempts).toEqual([
      [
        { role: 'user', content: '问题' },
        { role: 'assistant', content: '模型回答' },
      ],
    ]);
  });
});

class RejectingConversationStore implements ConversationStore {
  readonly appendAttempts: ChatMessage[][] = [];

  messages(): Promise<readonly ChatMessage[]> {
    return Promise.resolve([]);
  }

  append(_sessionId: string, messages: readonly ChatMessage[]): Promise<void> {
    this.appendAttempts.push([...messages]);
    return Promise.reject(new Error('存储故障'));
  }

  clear(): Promise<void> {
    return Promise.resolve();
  }
}
