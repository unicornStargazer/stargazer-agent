import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import {
  ChatApiError,
  deleteServerConversation,
  loadConversationHistory,
  sendChatMessage,
  streamChatMessage,
} from '../services/chat-api';
import type {
  AgentProfile,
  Conversation,
  ConversationMessage,
  FailedChatRequest,
  PendingChatRequest,
  TokenUsage,
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
  const syncingConversationIds = ref<string[]>([]);
  const notice = ref<string | undefined>();
  const initialActiveConversation = storedWorkspace.conversations.find(
    (conversation) => conversation.id === storedWorkspace.activeConversationId,
  );
  const selectedProfileId = ref(initialActiveConversation?.profileId ?? 'default');
  const availableProfileIds = ref<string[]>([]);

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

  function configureProfiles(
    profiles: readonly AgentProfile[],
    defaultProfileId: string | undefined,
  ): void {
    if (profiles.length === 0) {
      return;
    }
    availableProfileIds.value = profiles.map((profile) => profile.id);
    const fallbackProfileId =
      defaultProfileId !== undefined && availableProfileIds.value.includes(defaultProfileId)
        ? defaultProfileId
        : (profiles[0]?.id ?? 'default');
    const conversation = activeConversation.value;
    if (conversation === undefined) {
      selectedProfileId.value = fallbackProfileId;
      return;
    }
    if (availableProfileIds.value.includes(conversation.profileId)) {
      selectedProfileId.value = conversation.profileId;
      return;
    }
    conversation.profileId = fallbackProfileId;
    selectedProfileId.value = fallbackProfileId;
    persistWorkspace();
    setNotice('原模型已不可用，后续对话将使用默认模型继续。');
  }

  function selectProfile(profileId: string): void {
    if (
      !/^[a-zA-Z0-9_-]+$/.test(profileId) ||
      (availableProfileIds.value.length > 0 && !availableProfileIds.value.includes(profileId))
    ) {
      return;
    }
    const conversation = activeConversation.value;
    if (conversation?.profileId === profileId) {
      selectedProfileId.value = profileId;
      return;
    }
    selectedProfileId.value = profileId;
    if (conversation !== undefined) {
      conversation.profileId = profileId;
      persistWorkspace();
    }
  }

  function renameConversation(conversationId: string, title: string): boolean {
    const normalizedTitle = title.trim();
    const conversation = conversations.value.find((item) => item.id === conversationId);
    if (conversation === undefined || !normalizedTitle) {
      return false;
    }
    conversation.title = normalizedTitle.slice(0, 64);
    persistWorkspace();
    return true;
  }

  async function syncConversationHistory(conversationId: string): Promise<void> {
    const conversation = conversations.value.find((item) => item.id === conversationId);
    if (
      conversation === undefined ||
      pendingRequests.value[conversationId] !== undefined ||
      syncingConversationIds.value.includes(conversationId)
    ) {
      return;
    }
    syncingConversationIds.value.push(conversationId);
    try {
      const history = await loadConversationHistory(conversationId);
      if (history.length === 0 || pendingRequests.value[conversationId] !== undefined) {
        return;
      }
      const localMessages = [...conversation.messages];
      conversation.messages.splice(
        0,
        conversation.messages.length,
        ...history.map((message, index) => {
          const localMessage = localMessages[index];
          const canReuseLocalMessage =
            localMessage?.role === message.role && localMessage.content === message.content;
          return {
            id: canReuseLocalMessage ? localMessage.id : createIdentifier('message'),
            role: message.role,
            content: message.content,
            reasoning: message.reasoning,
            usage: message.usage,
            requestId:
              canReuseLocalMessage && message.role === 'user' ? localMessage.requestId : undefined,
          };
        }),
      );
      persistWorkspace();
    } catch (error: unknown) {
      setNotice(errorMessage(error, '无法同步服务端会话历史，已保留本地记录。'));
    } finally {
      syncingConversationIds.value = syncingConversationIds.value.filter(
        (currentId) => currentId !== conversationId,
      );
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
    let assistantMessageId: string | undefined;
    try {
      const conversation = conversations.value.find((item) => item.id === conversationId);
      if (conversation === undefined) {
        return;
      }
      const assistantMessage: ConversationMessage = {
        id: createIdentifier('message'),
        role: 'assistant',
        content: '',
      };
      assistantMessageId = assistantMessage.id;
      conversation.messages.push(assistantMessage);
      const chatRequest = {
        sessionId: conversationId,
        requestId: request.requestId,
        message: request.message,
        profileId: conversation.profileId,
      };
      const appendChunk = (chunk: string): void => {
        appendAssistantChunk(conversation, assistantMessage.id, chunk);
      };
      const appendReasoning = (chunk: string): void => {
        appendAssistantReasoning(conversation, assistantMessage.id, chunk);
      };
      const applyUsage = (usage: TokenUsage): void => {
        setAssistantUsage(conversation, assistantMessage.id, usage);
      };
      try {
        await streamChatMessage(chatRequest, appendChunk, {
          onReasoning: appendReasoning,
          onUsage: applyUsage,
        });
      } catch (error: unknown) {
        if (!(error instanceof ChatApiError) || error.code !== 'STREAMING_UNAVAILABLE') {
          throw error;
        }
        appendChunk((await sendChatMessage(chatRequest)).content);
      }
      if (!conversation.messages.find((message) => message.id === assistantMessage.id)?.content) {
        throw new Error('模型未返回文本内容');
      }
      conversation.updatedAt = new Date().toISOString();
      persistWorkspace();
    } catch (error: unknown) {
      const conversation = conversations.value.find((item) => item.id === conversationId);
      const assistantMessageIndex = conversation?.messages.findIndex(
        (message) => message.id === assistantMessageId,
      );
      if (
        conversation !== undefined &&
        assistantMessageIndex !== undefined &&
        assistantMessageIndex >= 0
      ) {
        conversation.messages.splice(assistantMessageIndex, 1);
      }
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
      selectedProfileId.value = conversations.value[0]?.profileId ?? selectedProfileId.value;
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
    syncingConversationIds,
    notice,
    selectedProfileId,
    activeConversation,
    sortedConversations,
    activePendingRequest,
    activeFailure,
    initialize,
    createNewConversation,
    selectConversation,
    configureProfiles,
    selectProfile,
    renameConversation,
    syncConversationHistory,
    deleteConversation,
    sendMessage,
    retryFailedRequest,
    clearNotice,
  };
});

function appendAssistantChunk(
  conversation: Conversation,
  assistantMessageId: string,
  chunk: string,
): void {
  const messageIndex = conversation.messages.findIndex(
    (message) => message.id === assistantMessageId,
  );
  const currentMessage = conversation.messages[messageIndex];
  if (messageIndex < 0 || currentMessage === undefined) {
    return;
  }
  conversation.messages[messageIndex] = {
    ...currentMessage,
    content: currentMessage.content + chunk,
  };
}

function appendAssistantReasoning(
  conversation: Conversation,
  assistantMessageId: string,
  chunk: string,
): void {
  updateAssistantMessage(conversation, assistantMessageId, (message) => ({
    ...message,
    reasoning: (message.reasoning ?? '') + chunk,
  }));
}

function setAssistantUsage(
  conversation: Conversation,
  assistantMessageId: string,
  usage: TokenUsage,
): void {
  updateAssistantMessage(conversation, assistantMessageId, (message) => ({ ...message, usage }));
}

function updateAssistantMessage(
  conversation: Conversation,
  assistantMessageId: string,
  update: (message: ConversationMessage) => ConversationMessage,
): void {
  const messageIndex = conversation.messages.findIndex(
    (message) => message.id === assistantMessageId,
  );
  const currentMessage = conversation.messages[messageIndex];
  if (messageIndex < 0 || currentMessage === undefined) {
    return;
  }
  conversation.messages[messageIndex] = update(currentMessage);
}

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
