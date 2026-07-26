import { describe, expect, it } from 'vitest';

import type { AgentProfile, Conversation } from '../types/chat';
import { createConversationFilename, createConversationMarkdown } from './conversation-export';

const conversation: Conversation = {
  id: 'session-export',
  profileId: 'support',
  title: '订单 / 排查记录',
  createdAt: '2026-07-26T08:00:00.000Z',
  updatedAt: '2026-07-26T08:01:00.000Z',
  messages: [
    { id: 'message-user', role: 'user', content: '订单现在是什么状态？' },
    { id: 'message-assistant', role: 'assistant', content: '**已发货**' },
  ],
};
const profile: AgentProfile = { id: 'support', name: '订单助手', model: 'test-model' };

describe('conversation export', () => {
  it('exports only the visible transcript and public Profile summary', () => {
    expect(createConversationMarkdown(conversation, profile)).toBe(
      '# 订单 / 排查记录\n\n> Agent: 订单助手\n> Model: test-model\n\n## 用户\n\n订单现在是什么状态？\n\n## 订单助手\n\n**已发货**\n',
    );
  });

  it('creates a filesystem-safe Markdown filename', () => {
    expect(createConversationFilename(' 订单 / 排查:*记录 ')).toBe('订单-排查-记录.md');
  });
});
