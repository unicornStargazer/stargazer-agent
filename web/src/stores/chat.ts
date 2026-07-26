import { computed, ref } from 'vue';
import { defineStore } from 'pinia';

import { deleteServerConversation, streamChatMessage } from '../services/chat-api';
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

  /**
   * 发送消息的异步函数
   * @param message - 要发送的消息内容
   * @returns Promise<void> - 无返回值的Promise
   */
  async function sendMessage(message: string): Promise<void> {
    // 获取当前活跃的对话
    const conversation = activeConversation.value;
    // 去除消息首尾空格后的规范化消息
    const normalizedMessage = message.trim();
    // 检查对话是否存在、消息是否为空、以及当前对话是否有待处理的请求
    if (
      conversation === undefined || // 对话不存在
      !normalizedMessage || // 消息为空
      pendingRequests.value[conversation.id] !== undefined // 当前对话已有待处理的请求
    ) {
      return; // 如果任一条件不满足，直接返回
    }

    // 创建唯一的请求ID
    const requestId = createIdentifier('request');
    // 将用户消息添加到对话中
    conversation.messages.push({
      id: createIdentifier('message'), // 创建消息唯一标识
      role: 'user', // 消息发送者角色为用户
      content: normalizedMessage, // 消息内容
      requestId, // 关联的请求ID
    });
    // 如果是新对话，则根据首条消息创建标题
    if (conversation.title === '新对话') {
      conversation.title = createConversationTitle(normalizedMessage);
    }
    // 更新对话的最后修改时间
    conversation.updatedAt = new Date().toISOString();
    // 持久化工作区状态
    persistWorkspace();
    // 请求助手回复
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

  /**
   * 请求助手响应的异步函数
   * @param conversationId 对话ID
   * @param request 待处理的聊天请求
   * @returns Promise<void>
   */
  async function requestAssistantResponse(
    conversationId: string, // 对话的唯一标识符
    request: PendingChatRequest, // 待处理的聊天请求对象
  ): Promise<void> {
    // 函数返回一个空Promise
    // 将请求添加到待处理请求列表中，并从失败请求列表中移除
    pendingRequests.value[conversationId] = request;
    delete failedRequests.value[conversationId];
    try {
      // 查找指定ID的对话
      const conversation = conversations.value.find((item) => item.id === conversationId);
      if (conversation === undefined) {
        return; // 如果对话不存在，直接返回
      }
      // 创建助手消息对象
      const assistantMessage: ConversationMessage = {
        id: createIdentifier('message'), // 生成消息唯一标识
        role: 'assistant', // 消息角色为助手
        content: '', // 初始内容为空
      };
      // 将助手消息添加到对话消息列表中
      conversation.messages.push(assistantMessage);
      // 流式获取聊天消息
      await streamChatMessage(
        {
          sessionId: conversationId, // 会话ID
          requestId: request.requestId, // 请求ID
          message: request.message, // 用户发送的消息
          profileId: conversation.profileId, // 用户配置ID
        },
        // 处理接收到的消息块
        (chunk) => {
          // 找到助手消息在列表中的位置
          const messageIndex = conversation.messages.findIndex(
            (message) => message.id === assistantMessage.id,
          );
          // 如果找到消息，更新其内容
          if (messageIndex >= 0) {
            conversation.messages[messageIndex] = {
              ...assistantMessage,
              content: (conversation.messages[messageIndex]?.content ?? '') + chunk, // 追加新内容
            };
          }
        },
      );
      // 检查助手消息是否有内容
      if (!conversation.messages.find((message) => message.id === assistantMessage.id)?.content) {
        throw new Error('模型未返回文本内容'); // 如果没有内容，抛出错误
      }
      // 更新对话的最后修改时间
      conversation.updatedAt = new Date().toISOString();
      // 持久化工作区数据
      persistWorkspace();
    } catch (error: unknown) {
      // 捕获错误
      // 查找对话
      const conversation = conversations.value.find((item) => item.id === conversationId);
      // 如果对话的最后一条消息是助手消息，则移除它
      if (conversation?.messages.at(-1)?.role === 'assistant') {
        conversation.messages.pop();
      }
      // 将请求添加到失败请求列表
      failedRequests.value[conversationId] = {
        ...request,
        description: errorMessage(error, '请求失败，请稍后重试。'), // 获取错误描述
      };
    } finally {
      // 无论成功或失败，都从待处理请求列表中移除当前请求
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
