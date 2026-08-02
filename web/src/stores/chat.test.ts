import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ChatApiError,
  deleteServerConversation,
  loadConversationHistory,
  sendChatMessage,
  streamChatMessage,
} from '../services/chat-api';
import type { ApiChatMessage, ApiConversationMessage } from '../types/chat';
import {
  ACTIVE_CONVERSATION_STORAGE_KEY,
  WORKSPACE_STORAGE_KEY,
} from '../utils/conversation-storage';
import { useChatStore } from './chat';

vi.mock('../services/chat-api', () => ({
  ChatApiError: class ChatApiError extends Error {
    constructor(
      readonly status: number,
      readonly code: string,
      message: string,
    ) {
      super(message);
    }
  },
  deleteServerConversation: vi.fn(),
  loadConversationHistory: vi.fn(),
  sendChatMessage: vi.fn(),
  streamChatMessage: vi.fn(),
}));

describe('chat store', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setActivePinia(createPinia());
    vi.resetAllMocks();
    vi.mocked(loadConversationHistory).mockResolvedValue([]);
  });

  it('writes a delayed response to its originating conversation after navigation', async () => {
    let resolveResponse: ((response: ApiChatMessage) => void) | undefined;
    const responsePromise = new Promise<ApiChatMessage>((resolve) => {
      resolveResponse = resolve;
    });
    vi.mocked(streamChatMessage).mockImplementationOnce(async (_request, onChunk) => {
      onChunk((await responsePromise).content);
    });
    const store = useChatStore();
    store.initialize();
    const originalConversationId = store.activeConversationId;
    expect(originalConversationId).toBeDefined();

    const pendingSend = store.sendMessage('第一条消息');
    await vi.waitFor(() => expect(streamChatMessage).toHaveBeenCalledOnce());
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
    vi.mocked(streamChatMessage)
      .mockRejectedValueOnce(new Error('模型暂时不可用'))
      .mockImplementationOnce((_request, onChunk) => Promise.resolve(onChunk('重试成功')));
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;
    expect(conversationId).toBeDefined();

    await store.sendMessage('需要重试的消息');
    const failedRequest = conversationId ? store.failedRequests[conversationId] : undefined;
    expect(failedRequest?.description).toBe('模型暂时不可用');
    expect(store.activeConversation?.messages).toHaveLength(1);

    await store.retryFailedRequest();

    expect(streamChatMessage).toHaveBeenCalledTimes(2);
    expect(vi.mocked(streamChatMessage).mock.calls[1]?.[0]).toEqual(
      vi.mocked(streamChatMessage).mock.calls[0]?.[0],
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

  it('keeps the current conversation when selecting another Profile after a message exists', async () => {
    vi.mocked(streamChatMessage).mockImplementationOnce((_request, onChunk) =>
      Promise.resolve(onChunk('回复')),
    );
    const store = useChatStore();
    store.initialize();
    const originalConversationId = store.activeConversationId;

    await store.sendMessage('第一条消息');
    store.selectProfile('detailed');

    expect(store.selectedProfileId).toBe('detailed');
    expect(store.activeConversationId).toBe(originalConversationId);
    expect(store.activeConversation).toMatchObject({ profileId: 'detailed' });
    expect(store.conversations.find((item) => item.id === originalConversationId)?.profileId).toBe(
      'detailed',
    );
  });

  it('updates the current empty conversation when selecting another Profile', () => {
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;

    store.selectProfile('detailed');

    expect(store.activeConversationId).toBe(conversationId);
    expect(store.activeConversation?.profileId).toBe('detailed');
    expect(store.selectedProfileId).toBe('detailed');
  });

  it('restores the active Profile from the stored conversation', () => {
    const storedConversation = {
      id: 'session-stored',
      profileId: 'detailed',
      title: '已保存会话',
      createdAt: '2026-07-26T08:00:00.000Z',
      updatedAt: '2026-07-26T08:00:00.000Z',
      messages: [],
    };
    window.localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify([storedConversation]));
    window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, storedConversation.id);

    const store = useChatStore();
    store.initialize();

    expect(store.selectedProfileId).toBe('detailed');
    expect(store.activeConversationId).toBe(storedConversation.id);
  });

  it('writes restored server history to its originating conversation after navigation', async () => {
    let resolveHistory: ((messages: readonly ApiConversationMessage[]) => void) | undefined;
    const historyPromise = new Promise<readonly ApiConversationMessage[]>((resolve) => {
      resolveHistory = resolve;
    });
    vi.mocked(loadConversationHistory).mockReturnValueOnce(historyPromise);
    const firstConversation = {
      id: 'session-first',
      profileId: 'default',
      title: '第一段对话',
      createdAt: '2026-07-26T08:00:00.000Z',
      updatedAt: '2026-07-26T08:00:00.000Z',
      messages: [{ id: 'message-local', role: 'user' as const, content: '本地记录' }],
    };
    const secondConversation = {
      ...firstConversation,
      id: 'session-second',
      title: '第二段对话',
      messages: [],
    };
    window.localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify([firstConversation, secondConversation]),
    );
    window.localStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, firstConversation.id);
    const store = useChatStore();
    store.initialize();

    const pendingSync = store.syncConversationHistory(firstConversation.id);
    store.selectConversation(secondConversation.id);
    if (resolveHistory === undefined) {
      throw new Error('History resolver was not initialized.');
    }
    resolveHistory([{ role: 'assistant', content: '服务端最终回复' }]);
    await pendingSync;

    expect(store.activeConversationId).toBe(secondConversation.id);
    expect(store.conversations.find((item) => item.id === firstConversation.id)?.messages).toEqual([
      expect.objectContaining({ role: 'assistant', content: '服务端最终回复' }),
    ]);
  });

  it('restores persisted reasoning and Token usage from server history', async () => {
    vi.mocked(loadConversationHistory).mockResolvedValueOnce([
      {
        role: 'assistant',
        content: '服务端回答',
        reasoning: '服务端思考过程',
        usage: { inputTokens: 11, outputTokens: 9, totalTokens: 20 },
      },
    ]);
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;

    await store.syncConversationHistory(conversationId ?? '');

    expect(store.activeConversation?.messages).toEqual([
      expect.objectContaining({
        role: 'assistant',
        content: '服务端回答',
        reasoning: '服务端思考过程',
        usage: { inputTokens: 11, outputTokens: 9, totalTokens: 20 },
      }),
    ]);
  });

  it('does not overwrite a request started while server history is loading', async () => {
    let resolveHistory: ((messages: readonly ApiConversationMessage[]) => void) | undefined;
    const historyPromise = new Promise<readonly ApiConversationMessage[]>((resolve) => {
      resolveHistory = resolve;
    });
    let finishStream: (() => void) | undefined;
    vi.mocked(loadConversationHistory).mockReturnValueOnce(historyPromise);
    vi.mocked(streamChatMessage).mockImplementationOnce((_request, onChunk) => {
      onChunk('新回复');
      return new Promise<void>((resolve) => {
        finishStream = resolve;
      });
    });
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;
    expect(conversationId).toBeDefined();

    const pendingSync = store.syncConversationHistory(conversationId ?? '');
    await vi.waitFor(() => expect(loadConversationHistory).toHaveBeenCalledOnce());
    const pendingSend = store.sendMessage('同步期间的新问题');
    await vi.waitFor(() => expect(streamChatMessage).toHaveBeenCalledOnce());
    if (resolveHistory === undefined || finishStream === undefined) {
      throw new Error('Test request resolvers were not initialized.');
    }
    resolveHistory([{ role: 'assistant', content: '旧服务端记录' }]);
    await pendingSync;
    finishStream();
    await pendingSend;

    expect(
      store.activeConversation?.messages.map(({ role, content }) => ({ role, content })),
    ).toEqual([
      { role: 'user', content: '同步期间的新问题' },
      { role: 'assistant', content: '新回复' },
    ]);
  });

  it('falls back to the non-streaming endpoint only when streaming is unavailable', async () => {
    vi.mocked(streamChatMessage).mockRejectedValueOnce(
      new ChatApiError(501, 'STREAMING_UNAVAILABLE', '当前服务未启用流式聊天'),
    );
    vi.mocked(sendChatMessage).mockResolvedValueOnce({ role: 'assistant', content: '普通回复' });
    const store = useChatStore();
    store.initialize();

    await store.sendMessage('使用降级通道');

    expect(sendChatMessage).toHaveBeenCalledOnce();
    expect(store.activeConversation?.messages.at(-1)).toMatchObject({
      role: 'assistant',
      content: '普通回复',
    });
  });

  it('renames a conversation and persists the normalized title', () => {
    const store = useChatStore();
    store.initialize();
    const conversationId = store.activeConversationId;
    expect(conversationId).toBeDefined();

    const renamed = store.renameConversation(conversationId ?? '', '  项目排查记录  ');

    expect(renamed).toBe(true);
    expect(store.activeConversation?.title).toBe('项目排查记录');
    expect(window.localStorage.getItem(WORKSPACE_STORAGE_KEY)).toContain('项目排查记录');
  });
});
