<script setup lang="ts">
import { storeToRefs } from 'pinia';
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';

import ChatComposer from './components/chat/ChatComposer.vue';
import ChatEmptyState from './components/chat/ChatEmptyState.vue';
import ChatMessages from './components/chat/ChatMessages.vue';
import ChatHeader from './components/layout/ChatHeader.vue';
import ChatSidebar from './components/layout/ChatSidebar.vue';
import { useAgentStatus } from './composables/useAgentStatus';
import { useChatStore } from './stores/chat';

interface ComposerExposed {
  focus(): void;
}

const chatStore = useChatStore();
chatStore.initialize();

const {
  activeConversation,
  activeConversationId,
  activeFailure,
  activePendingRequest,
  deletingConversationIds,
  notice,
  pendingRequests,
  sortedConversations,
} = storeToRefs(chatStore);
const { status } = useAgentStatus();

const sidebarOpen = ref(false);
const draft = ref('');
const chatScroll = ref<HTMLElement>();
const composer = ref<ComposerExposed>();
let noticeTimeout: number | undefined;

const pendingConversationIds = computed(() => Object.keys(pendingRequests.value));
const activeBusy = computed(() => activePendingRequest.value !== undefined);
const activeDeleting = computed(() => {
  const conversationId = activeConversationId.value;
  return conversationId !== undefined && deletingConversationIds.value.includes(conversationId);
});
const activeMessageCount = computed(() => activeConversation.value?.messages.length ?? 0);

function createConversation(): void {
  chatStore.createNewConversation();
  closeSidebar();
  draft.value = '';
  focusComposer();
}

function selectConversation(conversationId: string): void {
  chatStore.selectConversation(conversationId);
  closeSidebar();
  draft.value = '';
  focusComposer();
}

function deleteConversation(conversationId: string): void {
  void chatStore.deleteConversation(conversationId);
}

function deleteActiveConversation(): void {
  const conversationId = activeConversationId.value;
  if (conversationId !== undefined) {
    deleteConversation(conversationId);
  }
}

function sendMessage(): void {
  const message = draft.value.trim();
  if (!message || activeBusy.value) {
    return;
  }
  draft.value = '';
  void chatStore.sendMessage(message);
}

function choosePrompt(prompt: string): void {
  draft.value = prompt;
  focusComposer();
}

function focusComposer(): void {
  void nextTick(() => composer.value?.focus());
}

function closeSidebar(): void {
  sidebarOpen.value = false;
}

function handleGlobalKeydown(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    createConversation();
  }
  if (event.key === 'Escape') {
    closeSidebar();
  }
}

function scrollMessagesToBottom(smooth = true): void {
  void nextTick(() => {
    chatScroll.value?.scrollTo({
      top: chatScroll.value.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  });
}

watch(
  [activeConversationId, activeMessageCount, activeBusy],
  ([currentConversationId], [previousConversationId]) => {
    scrollMessagesToBottom(currentConversationId === previousConversationId);
  },
);

watch(notice, (message) => {
  window.clearTimeout(noticeTimeout);
  if (message !== undefined) {
    noticeTimeout = window.setTimeout(chatStore.clearNotice, 2600);
  }
});

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown);
  focusComposer();
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown);
  window.clearTimeout(noticeTimeout);
});
</script>

<template>
  <div class="app-shell">
    <div
      class="sidebar-backdrop"
      :class="{ visible: sidebarOpen }"
      :aria-hidden="!sidebarOpen"
      @click="closeSidebar"
    ></div>

    <ChatSidebar
      :class="{ open: sidebarOpen }"
      :conversations="sortedConversations"
      :active-conversation-id="activeConversationId"
      :pending-conversation-ids="pendingConversationIds"
      :deleting-conversation-ids="deletingConversationIds"
      :status="status"
      @close="closeSidebar"
      @create="createConversation"
      @select="selectConversation"
      @delete="deleteConversation"
    />

    <main class="main-panel">
      <ChatHeader
        :title="activeConversation?.title ?? '新对话'"
        :busy="activeBusy"
        :deleting="activeDeleting"
        @open-sidebar="sidebarOpen = true"
        @delete="deleteActiveConversation"
      />

      <section ref="chatScroll" class="chat-scroll" aria-label="对话消息">
        <ChatEmptyState v-if="activeMessageCount === 0 && !activeBusy" @choose="choosePrompt" />
        <ChatMessages v-else :messages="activeConversation?.messages ?? []" :busy="activeBusy" />
      </section>

      <ChatComposer
        ref="composer"
        v-model="draft"
        :busy="activeBusy"
        :failure="activeFailure"
        @send="sendMessage"
        @retry="chatStore.retryFailedRequest"
      />
    </main>

    <div v-if="notice" class="toast" role="status" aria-live="polite">{{ notice }}</div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  width: 100%;
  height: 100dvh;
}

.main-panel {
  position: relative;
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: 64px minmax(0, 1fr) auto;
  background: var(--page);
}

.chat-scroll {
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-color: #c5cbc6 transparent;
  scrollbar-width: thin;
}

.sidebar-backdrop {
  display: none;
}

.toast {
  position: fixed;
  z-index: 60;
  right: 20px;
  bottom: 20px;
  max-width: min(360px, calc(100% - 40px));
  padding: 10px 13px;
  color: #f5f7f5;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
  background: #252a27;
  border: 1px solid #3d4540;
  border-radius: 7px;
  box-shadow: var(--shadow-soft);
}

@media (max-width: 900px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar-backdrop {
    position: fixed;
    z-index: 25;
    inset: 0;
    display: block;
    visibility: hidden;
    background: rgb(15 18 16 / 44%);
    opacity: 0;
    transition:
      opacity 190ms ease,
      visibility 190ms ease;
  }

  .sidebar-backdrop.visible {
    visibility: visible;
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .main-panel {
    grid-template-rows: 58px minmax(0, 1fr) auto;
  }

  .toast {
    right: 12px;
    bottom: 12px;
    max-width: calc(100% - 24px);
  }
}
</style>
