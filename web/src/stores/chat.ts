import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { deleteServerConversation, sendChatMessage } from '../services/chat-api';
import type {
  Conversation,
  ConversationMessage,
  FailedChatRequest,
  PendingChatRequest,
} from '../types/chat';
import { loadWorkspace, saveWorkspace } from '../utils/conversation-storage';
import { createIdentifier } from '../utils/identifiers';

const MAX_TITLE_LENGTH = 32;

export const useChatStore = defineStore('chat', () => {
  const storedWorkspace = loadWorkspace();
  const conversations = ref<Conversation[]>(storedWorkspace.conversations);
  const activeConversationId = ref<string | undefined>(storedWorkspace.activeConversationId);
  const pendingRequests = ref<Record<string, PendingChatRequest>>({});
  const failedRequests = ref<Record<string, FailedChatRequest>>({});
  const deletingConversationIds = ref<string[]>([]);
  const notice = ref<string | undefined>();
  const selectedProfileId = ref('default');

  const activeConversation = computed(() =>
    conversations.value.find((conversation) => conversation.id === activeConversationId.value),
  );
  const sortedConversations = computed(() =>
    [...conversations.value].sort(
      (first, second) => Date.parse(second.updatedAt) - Date.parse(first.updatedAt),
    ),
  );
  const activePendingRequest = computed(() => {
    const conversationId = activeConversationId.value;
    return conversationId === undefined ? undefined : pendingRequests.value[conversationId];
  });
  const activeFailure = computed(() => {
    const conversationId = activeConversationId.value;
    return conversationId === undefined ? undefined : failedRequests.value[conversationId];
  });

  function initialize(): void {
    const activeExists = conversations.value.some(
      (conversation) => conversation.id === activeConversationId.value,
    );
    if (!activeExists) {
      const conversation = createConversation(selectedProfileId.value);
      conversations.value.unshift(conversation);
      activeConversationId.value = conversation.id;
      persistWorkspace();
    }
  }

  function createNewConversation(): void {
    if (activeConversation.value?.messages.length === 0) {
      return;
    }
    const conversation = createConversation(selectedProfileId.value);
    conversations.value.unshift(conversation);
    activeConversationId.value = conversation.id;
    persistWorkspace();
  }

  function selectConversation(conversationId: string): void {
    const conversation = conversations.value.find((item) => item.id === conversationId);
    if (conversation === undefined) {
      return;
    }
    activeConversationId.value = conversationId;
    selectedProfileId.value = conversation.profileId;
    persistWorkspace();
  }

  function selectProfile(profileId: string): void {
    if (!/^[a-zA-Z0-9_-]+$/.test(profileId) || profileId === selectedProfileId.value) {
      return;
    }
    selectedProfileId.value = profileId;
    // 已有消息的会话必须维持原 Profile；切换时主动开始新会话而不是让用户碰到冲突错误。
    if (activeConversation.value?.messages.length) {
      const conversation = createConversation(profileId);
      conversations.value.unshift(conversation);
      activeConversationId.value = conversation.id;
      persistWorkspace();
    }
  }

  async function deleteConversation(conversationId: string): Promise<void> {
    if (pendingRequests.value[conversationId] !== undefined) {
      setNotice('等待当前回复完成后再删除对话。');
      return;
    }
    if (deletingConversationIds.value.includes(conversationId)) {
      return;
    }

    deletingConversationIds.value.push(conversationId);
    try {
      await deleteServerConversation(conversationId);
      conversations.value = conversations.value.filter(
        (conversation) => conversation.id !== conversationId,
      );
      delete failedRequests.value[conversationId];
      ensureConversationAfterDelete(conversationId);
      persistWorkspace();
      setNotice('对话已删除。');
    } catch (error: unknown) {
      setNotice(errorMessage(error, '删除失败，请稍后重试。'));
    } finally {
      deletingConversationIds.value = deletingConversationIds.value.filter(
        (currentId) => currentId !== conversationId,
      );
    }
  }

  async function sendMessage(message: string): Promise<void> {
    const conversation = activeConversation.value;
    const normalizedMessage = message.trim();
    if (
      conversation === undefined ||
      !normalizedMessage ||
      pendingRequests.value[conversation.id] !== undefined
    ) {
      return;
    }

    const requestId = createIdentifier('request');
    conversation.messages.push({
      id: createIdentifier('message'),
      role: 'user',
      content: normalizedMessage,
      requestId,
    });
    if (conversation.title === '新对话') {
      conversation.title = createConversationTitle(normalizedMessage);
    }
    conversation.updatedAt = new Date().toISOString();
    persistWorkspace();
    await requestAssistantResponse(conversation.id, { requestId, message: normalizedMessage });
  }

  async function retryFailedRequest(): Promise<void> {
    const conversationId = activeConversationId.value;
    if (conversationId === undefined) {
      return;
    }
    const failedRequest = failedRequests.value[conversationId];
    if (failedRequest === undefined || pendingRequests.value[conversationId] !== undefined) {
      return;
    }
    await requestAssistantResponse(conversationId, failedRequest);
  }

  function clearNotice(): void {
    notice.value = undefined;
  }

  async function requestAssistantResponse(
    conversationId: string,
    request: PendingChatRequest,
  ): Promise<void> {
    pendingRequests.value[conversationId] = request;
    delete failedRequests.value[conversationId];
    try {
      const conversation = conversations.value.find((item) => item.id === conversationId);
      if (conversation === undefined) {
        return;
      }
      const response = await sendChatMessage({
        sessionId: conversationId,
        requestId: request.requestId,
        message: request.message,
        profileId: conversation.profileId,
      });
      const assistantMessage: ConversationMessage = {
        id: createIdentifier('message'),
        role: 'assistant',
        content: response.content,
      };
      conversation.messages.push(assistantMessage);
      conversation.updatedAt = new Date().toISOString();
      persistWorkspace();
    } catch (error: unknown) {
      failedRequests.value[conversationId] = {
        ...request,
        description: errorMessage(error, '请求失败，请稍后重试。'),
      };
    } finally {
      delete pendingRequests.value[conversationId];
    }
  }

  function ensureConversationAfterDelete(deletedConversationId: string): void {
    if (conversations.value.length === 0) {
      conversations.value.push(createConversation(selectedProfileId.value));
    }
    if (activeConversationId.value === deletedConversationId) {
      activeConversationId.value = conversations.value[0]?.id;
    }
  }

  function persistWorkspace(): void {
    try {
      saveWorkspace({
        conversations: conversations.value,
        activeConversationId: activeConversationId.value,
      });
    } catch {
      setNotice('浏览器存储空间不足，对话记录可能无法保留。');
    }
  }

  function setNotice(message: string): void {
    notice.value = message;
  }

  return {
    conversations,
    activeConversationId,
    pendingRequests,
    failedRequests,
    deletingConversationIds,
    notice,
    selectedProfileId,
    activeConversation,
    sortedConversations,
    activePendingRequest,
    activeFailure,
    initialize,
    createNewConversation,
    selectConversation,
    selectProfile,
    deleteConversation,
    sendMessage,
    retryFailedRequest,
    clearNotice,
  };
});

function createConversation(profileId: string): Conversation {
  const now = new Date().toISOString();
  return {
    id: createIdentifier('session'),
    profileId,
    title: '新对话',
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

function createConversationTitle(message: string): string {
  const firstLine = message.split(/\r?\n/, 1)[0]?.trim() ?? '';
  return firstLine.length > MAX_TITLE_LENGTH
    ? `${firstLine.slice(0, MAX_TITLE_LENGTH)}…`
    : firstLine;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
