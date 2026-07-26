import { beforeEach, describe, expect, it } from 'vitest';

import type { Conversation } from '../types/chat';
import {
  ACTIVE_CONVERSATION_STORAGE_KEY,
  loadWorkspace,
  saveWorkspace,
  WORKSPACE_STORAGE_KEY,
} from './conversation-storage';

const storedConversation: Conversation = {
  id: 'session-existing',
  profileId: 'default',
  title: '历史对话',
  createdAt: '2026-07-25T08:00:00.000Z',
  updatedAt: '2026-07-25T08:01:00.000Z',
  messages: [
    {
      id: 'message-user',
      role: 'user',
      content: '你好',
      requestId: 'request-existing',
    },
    { id: 'message-assistant', role: 'assistant', content: '你好，有什么可以帮你？' },
  ],
};

describe('conversation storage', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('loads the existing storage keys and message schema', () => {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify([storedConversation]));
    window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, storedConversation.id);

    expect(loadWorkspace()).toEqual({
      conversations: [storedConversation],
      activeConversationId: storedConversation.id,
    });
  });

  it('persists a bounded workspace using the compatible schema', () => {
    const conversations = Array.from({ length: 55 }, (_, index) => ({
      ...storedConversation,
      id: `session-${String(index)}`,
    }));

    saveWorkspace({ conversations, activeConversationId: 'session-0' });

    const savedValue = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    expect(savedValue).not.toBeNull();
    expect(JSON.parse(savedValue ?? '[]')).toHaveLength(50);
    expect(window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY)).toBe('session-0');
  });

  it('ignores malformed stored values instead of breaking initialization', () => {
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, '{invalid json');

    expect(loadWorkspace()).toEqual({ conversations: [], activeConversationId: undefined });
  });
});
