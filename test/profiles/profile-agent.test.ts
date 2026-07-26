/** 验证受控 Profile 注册表与会话绑定，不触发真实模型网络请求。 */

import { describe, expect, it } from 'vitest';

import { InMemoryConversationStore } from '../../src/chat/index.js';
import { FakeChatModel } from '../../src/providers/index.js';
import { ConversationProfileConflictError, ProfileAgent } from '../../src/profiles/index.js';

describe('ProfileAgent', () => {
  it('只暴露安全摘要，并按选定 Profile 生成系统提示', async () => {
    const store = new InMemoryConversationStore();
    const profiles = [
      { id: 'concise', name: '简洁助手', model: 'model-a', systemPrompt: '回答简洁' },
      { id: 'detailed', name: '详细助手', model: 'model-b', systemPrompt: '回答详细' },
    ];
    const models = new Map(profiles.map((profile) => [profile.id, new FakeChatModel(['回复'])]));
    const agent = new ProfileAgent({
      profiles,
      defaultProfileId: 'concise',
      conversationStore: store,
      createModel: (profile) => models.get(profile.id)!,
    });

    await agent.chat('session-1', 'detailed', '你好');

    expect(agent.profiles()).toEqual([
      { id: 'concise', name: '简洁助手', model: 'model-a' },
      { id: 'detailed', name: '详细助手', model: 'model-b' },
    ]);
    expect(models.get('detailed')?.requests[0]).toEqual([
      { role: 'system', content: '回答详细' },
      { role: 'user', content: '你好' },
    ]);
    await expect(store.profileId('session-1')).resolves.toBe('detailed');
  });

  it('拒绝在已有历史的会话中切换 Profile', async () => {
    const store = new InMemoryConversationStore();
    const agent = new ProfileAgent({
      profiles: [
        { id: 'first', name: '第一个', model: 'model-a' },
        { id: 'second', name: '第二个', model: 'model-b' },
      ],
      defaultProfileId: 'first',
      conversationStore: store,
      createModel: () => new FakeChatModel(['回复']),
    });

    await agent.chat('session-1', 'first', '第一条');

    await expect(agent.chat('session-1', 'second', '第二条')).rejects.toBeInstanceOf(
      ConversationProfileConflictError,
    );
  });
});
