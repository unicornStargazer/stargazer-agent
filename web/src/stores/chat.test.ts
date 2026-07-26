import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { deleteServerConversation, sendChatMessage } from '../services/chat-api';
import type { ApiChatMessage } from '../types/chat';
import { useChatStore } from './chat';

vi.mock('../services/chat-api', () => ({
  deleteServerConversation: vi.fn(),
  sendChatMessage: vi.fn(),
}));

describe('chat store', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
    vi.resetAllMocks();
  });

  it('writes a delayed response to its originating conversation after navigation', async () => {
    let resolveResponse: ((response: ApiChatMessage) => void) | undefined;
    const responsePromise = new Promise<ApiChatMessage>((resolve) => {
      resolveResponse = resolve;
    });
    vi.mocked(sendChatMessage).mockReturnValueOnce(responsePromise);
    const store = useChatStore();
    store.initialize();
    const originalConversationId = store.activeConversationId;
    expect(originalConversationId).toBeDefined();

    const pendingSend = store.sendMessage('第一条消息');
    await vi.waitFor(() => expect(sendChatMessage).toHaveBeenCalledOnce());
    store.createNewConversation();
    const newConversationId = store.activeConversationId;
    expect(newConversationId).not.toBe(originalConversationId);

    if (resolveResponse === undefined) {
      throw new Error('response resolver was not initialized');
    }
    resolveResponse({ role: 'assistant', content: '延迟回复' });
    await pendingSend;

    const originalConversation = store.conversations.find(
      (conversation) => conversation.id === originalConversationId,
    );
    const newConversation = store.conversations.find(
      (conversation) => conversation.id === newConversationId,
    );
    expect(originalConversation?.messages.map(({ role, content }) => ({ role, content }))).toEqual([
      { role: 'user', content: '第一条消息' },
      { role: 'assistant', content: '延迟回复' },
    ]);
    expect(newConversation?.messages).toEqual([]);
  });

  it('retries the same request without duplicating the user message', async () => {
    vi.mocked(sendChatMessage)
      .mockRejectedValueOnce(new Error('模型暂时不可用'))
      .mockResolvedValueOnce({ role: 'assistant', content: '重试成功' });
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;
    expect(conversationId).toBeDefined();

    await store.sendMessage('需要重试的消息');
    const failedRequest = conversationId ? store.failedRequests[conversationId] : undefined;
    expect(failedRequest?.description).toBe('模型暂时不可用');
    expect(store.activeConversation?.messages).toHaveLength(1);

    await store.retryFailedRequest();

    expect(sendChatMessage).toHaveBeenCalledTimes(2);
    expect(vi.mocked(sendChatMessage).mock.calls[1]?.[0]).toEqual(
      vi.mocked(sendChatMessage).mock.calls[0]?.[0],
    );
    expect(
      store.activeConversation?.messages.map(({ role, content }) => ({ role, content })),
    ).toEqual([
      { role: 'user', content: '需要重试的消息' },
      { role: 'assistant', content: '重试成功' },
    ]);
    expect(conversationId ? store.failedRequests[conversationId] : undefined).toBeUndefined();
  });

  it('keeps a conversation when server deletion fails', async () => {
    vi.mocked(deleteServerConversation).mockRejectedValueOnce(new Error('服务端拒绝删除'));
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;
    expect(conversationId).toBeDefined();

    if (conversationId === undefined) {
      throw new Error('conversation was not initialized');
    }
    await store.deleteConversation(conversationId);

    expect(store.conversations.some((conversation) => conversation.id === conversationId)).toBe(
      true,
    );
    expect(store.notice).toBe('服务端拒绝删除');
    expect(store.deletingConversationIds).toEqual([]);
  });

  it('starts a new conversation when selecting another Profile after a message exists', async () => {
    vi.mocked(sendChatMessage).mockResolvedValueOnce({ role: 'assistant', content: '回复' });
    const store = useChatStore();
    store.initialize();
    const originalConversationId = store.activeConversationId;

    await store.sendMessage('第一条消息');
    store.selectProfile('detailed');

    expect(store.selectedProfileId).toBe('detailed');
    expect(store.activeConversationId).not.toBe(originalConversationId);
    expect(store.activeConversation).toMatchObject({ profileId: 'detailed', messages: [] });
    expect(store.conversations.find((item) => item.id === originalConversationId)?.profileId).toBe(
      'default',
    );
  });
});
