<script setup lang="ts">
import {
  Check,
  ChevronsUpDown,
  LoaderCircle,
  MessageSquare,
  PanelLeftClose,
  Pencil,
  Search,
  Sparkles,
  SquarePen,
  Trash2,
  X,
} from '@lucide/vue';
import { computed, nextTick, ref } from 'vue';

import type { AgentViewStatus, Conversation } from '../../types/chat';
import { formatConversationTime } from '../../utils/date';

const props = defineProps<{
  conversations: readonly Conversation[];
  activeConversationId: string | undefined;
  pendingConversationIds: readonly string[];
  deletingConversationIds: readonly string[];
  syncingConversationIds: readonly string[];
  status: AgentViewStatus;
}>();

const emit = defineEmits<{
  close: [];
  create: [];
  select: [conversationId: string];
  delete: [conversationId: string];
  rename: [conversationId: string, title: string];
}>();

const sidebar = ref<HTMLElement>();
const searchQuery = ref('');
const editingConversationId = ref<string>();
const editingTitle = ref('');
const filteredConversations = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase('zh-CN');
  if (!query) {
    return props.conversations;
  }
  return props.conversations.filter(
    (conversation) =>
      conversation.title.toLocaleLowerCase('zh-CN').includes(query) ||
      conversation.messages.some((message) =>
        message.content.toLocaleLowerCase('zh-CN').includes(query),
      ),
  );
});

function isUnavailable(conversationId: string): boolean {
  return (
    props.pendingConversationIds.includes(conversationId) ||
    props.deletingConversationIds.includes(conversationId)
  );
}

function startRename(conversation: Conversation): void {
  editingConversationId.value = conversation.id;
  editingTitle.value = conversation.title;
  void nextTick(() => {
    const input = sidebar.value?.querySelector<HTMLInputElement>('input[data-renaming="true"]');
    input?.focus();
    input?.select();
  });
}

function submitRename(): void {
  const conversationId = editingConversationId.value;
  const title = editingTitle.value.trim();
  if (conversationId === undefined || !title) {
    return;
  }
  emit('rename', conversationId, title);
  cancelRename();
}

function cancelRename(): void {
  editingConversationId.value = undefined;
  editingTitle.value = '';
}
</script>

<template>
  <aside ref="sidebar" class="sidebar" aria-label="会话导航">
    <div class="brand-row">
      <a class="brand" href="/" aria-label="Stargazer Agent 首页">
        <span class="brand-mark" aria-hidden="true"><Sparkles /></span>
        <span>
          <strong>Stargazer</strong>
          <small>Agent Workspace</small>
        </span>
      </a>
      <button
        class="icon-button sidebar-close"
        type="button"
        aria-label="关闭会话导航"
        title="关闭会话导航"
        @click="emit('close')"
      >
        <PanelLeftClose />
      </button>
    </div>

    <button class="new-chat-button" type="button" @click="emit('create')">
      <SquarePen />
      <span>新对话</span>
    </button>

    <div class="conversation-search">
      <Search aria-hidden="true" />
      <input v-model="searchQuery" type="search" aria-label="搜索会话" placeholder="搜索会话" />
      <button
        v-if="searchQuery"
        type="button"
        aria-label="清除搜索"
        title="清除搜索"
        @click="searchQuery = ''"
      >
        <X />
      </button>
    </div>

    <nav class="conversation-navigation" aria-label="历史会话">
      <div class="section-label">{{ searchQuery.trim() ? '搜索结果' : '最近对话' }}</div>
      <div class="conversation-list">
        <div
          v-for="conversation in filteredConversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === activeConversationId }"
        >
          <form
            v-if="editingConversationId === conversation.id"
            class="conversation-rename-form"
            @submit.prevent="submitRename"
          >
            <input
              v-model="editingTitle"
              data-renaming="true"
              maxlength="64"
              :aria-label="`重命名对话：${conversation.title}`"
              @keydown.escape.prevent="cancelRename"
            />
            <button type="submit" aria-label="保存名称" title="保存名称"><Check /></button>
            <button type="button" aria-label="取消重命名" title="取消重命名" @click="cancelRename">
              <X />
            </button>
          </form>
          <button
            v-else
            type="button"
            class="conversation-select"
            :aria-current="conversation.id === activeConversationId ? 'page' : undefined"
            @click="emit('select', conversation.id)"
          >
            <MessageSquare />
            <span>
              <strong>{{ conversation.title }}</strong>
              <small>
                <LoaderCircle
                  v-if="syncingConversationIds.includes(conversation.id)"
                  class="sync-indicator"
                  aria-hidden="true"
                />
                {{ formatConversationTime(conversation.updatedAt) }}
              </small>
            </span>
          </button>
          <button
            v-if="editingConversationId !== conversation.id"
            type="button"
            class="conversation-rename"
            :aria-label="`重命名对话：${conversation.title}`"
            title="重命名对话"
            :disabled="isUnavailable(conversation.id)"
            @click.stop="startRename(conversation)"
          >
            <Pencil />
          </button>
          <button
            v-if="editingConversationId !== conversation.id"
            type="button"
            class="conversation-delete"
            :aria-label="`删除对话：${conversation.title}`"
            title="删除对话"
            :disabled="isUnavailable(conversation.id)"
            @click.stop="emit('delete', conversation.id)"
          >
            <Trash2 />
          </button>
        </div>
        <div v-if="filteredConversations.length === 0" class="conversation-empty">
          没有匹配的对话
        </div>
      </div>
    </nav>

    <div class="sidebar-footer">
      <div class="agent-status">
        <span class="status-indicator" :class="status.state" aria-hidden="true"></span>
        <span class="status-copy">
          <strong>{{ status.label }}</strong>
          <small>{{ status.model }}</small>
        </span>
        <ChevronsUpDown aria-hidden="true" />
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  z-index: 30;
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 20px 14px 14px;
  color: #f4f6f4;
  background: var(--sidebar);
  border-right: 1px solid #303531;
}

.brand-row,
.brand,
.new-chat-button,
.conversation-select,
.agent-status {
  display: flex;
  align-items: center;
}

.brand-row {
  min-height: 42px;
  justify-content: space-between;
  padding: 0 4px 0 6px;
}

.brand {
  min-width: 0;
  gap: 11px;
  color: inherit;
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  place-items: center;
  color: #f4f7f5;
  background: var(--accent);
  border: 1px solid #568b76;
  border-radius: 7px;
}

.brand-mark :deep(svg) {
  width: 17px;
  height: 17px;
}

.brand > span:last-child,
.status-copy,
.conversation-select > span {
  display: grid;
  min-width: 0;
}

.brand > span:last-child {
  gap: 1px;
}

.brand strong {
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand small {
  overflow: hidden;
  color: #9da69f;
  font-size: 10px;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.sidebar-close {
  display: none;
  color: #aeb6b0;
}

.sidebar-close:hover {
  color: #fff;
  background: var(--sidebar-hover);
}

.new-chat-button {
  width: 100%;
  min-height: 42px;
  gap: 10px;
  margin-top: 24px;
  padding: 0 11px;
  color: #f6f7f6;
  background: var(--accent);
  border: 1px solid #4c806c;
  border-radius: 7px;
  transition: background-color 150ms ease;
}

.conversation-search {
  display: grid;
  min-height: 36px;
  grid-template-columns: 16px minmax(0, 1fr) 24px;
  align-items: center;
  gap: 7px;
  margin-top: 12px;
  padding: 0 7px 0 10px;
  color: #89938c;
  background: #252a27;
  border: 1px solid #363c38;
  border-radius: 6px;
}

.conversation-search:focus-within {
  border-color: #5d786b;
}

.conversation-search > svg,
.conversation-search button svg {
  width: 14px;
  height: 14px;
}

.conversation-search input {
  min-width: 0;
  color: #eef1ef;
  font: inherit;
  font-size: 11px;
  background: transparent;
  border: 0;
  outline: 0;
}

.conversation-search input::placeholder {
  color: #78817b;
}

.conversation-search input::-webkit-search-cancel-button {
  display: none;
}

.conversation-search button {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  color: #8f9992;
  background: transparent;
  border-radius: 4px;
}

.conversation-search button:hover {
  color: #fff;
  background: var(--sidebar-hover);
}

.new-chat-button:hover {
  background: #3a7861;
}

.new-chat-button span {
  flex: 1;
  text-align: left;
}

.conversation-navigation {
  min-height: 0;
  flex: 1;
  margin-top: 18px;
  overflow-y: auto;
  scrollbar-color: #505751 transparent;
  scrollbar-width: thin;
}

.section-label {
  padding: 0 9px 9px;
  color: #858f88;
  font-size: 11px;
  font-weight: 650;
}

.conversation-list {
  display: grid;
  gap: 3px;
}

.conversation-item {
  position: relative;
  display: flex;
  min-width: 0;
  align-items: center;
  border-radius: 6px;
}

.conversation-item:hover {
  background: var(--sidebar-hover);
}

.conversation-item.active {
  background: var(--sidebar-active);
}

.conversation-select {
  min-width: 0;
  min-height: 48px;
  flex: 1;
  gap: 10px;
  padding: 6px 66px 6px 9px;
  color: #d9deda;
  text-align: left;
  background: transparent;
}

.conversation-select > :deep(svg) {
  width: 16px;
  height: 16px;
  color: #8d9790;
}

.conversation-select > span {
  gap: 2px;
}

.conversation-select strong,
.conversation-select small,
.status-copy strong,
.status-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-select strong {
  font-size: 13px;
  font-weight: 500;
}

.conversation-select small {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #89928c;
  font-size: 10px;
}

.conversation-rename,
.conversation-delete {
  position: absolute;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #929b95;
  background: transparent;
  border-radius: 5px;
  opacity: 0;
}

.conversation-rename {
  right: 33px;
}

.conversation-delete {
  right: 5px;
}

.conversation-rename :deep(svg),
.conversation-delete :deep(svg) {
  width: 14px;
  height: 14px;
}

.conversation-item:hover .conversation-rename,
.conversation-item:hover .conversation-delete,
.conversation-item.active .conversation-rename,
.conversation-item.active .conversation-delete,
.conversation-rename:focus-visible,
.conversation-delete:focus-visible {
  opacity: 1;
}

.conversation-rename:not(:disabled):hover {
  color: #dbe9e1;
  background: #3c4740;
}

.conversation-delete:not(:disabled):hover {
  color: #ffc6bd;
  background: #51312e;
}

.conversation-rename-form {
  display: grid;
  width: 100%;
  min-height: 48px;
  grid-template-columns: minmax(0, 1fr) 28px 28px;
  align-items: center;
  gap: 3px;
  padding: 6px;
}

.conversation-rename-form input {
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  color: #f0f3f1;
  font: inherit;
  font-size: 12px;
  background: #202421;
  border: 1px solid #5a7165;
  border-radius: 5px;
  outline: 0;
}

.conversation-rename-form button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #b2bcb5;
  background: transparent;
  border-radius: 5px;
}

.conversation-rename-form button:hover {
  color: #fff;
  background: var(--sidebar-hover);
}

.conversation-rename-form button svg {
  width: 14px;
  height: 14px;
}

.conversation-empty {
  padding: 18px 9px;
  color: #7f8982;
  font-size: 11px;
  text-align: center;
}

.sync-indicator {
  width: 11px;
  height: 11px;
  animation: spin 850ms linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.sidebar-footer {
  padding-top: 12px;
  border-top: 1px solid #343936;
}

.agent-status {
  min-width: 0;
  gap: 10px;
  padding: 8px;
}

.agent-status > :deep(svg) {
  width: 15px;
  height: 15px;
  color: #78827b;
}

.status-indicator {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  background: #7f8882;
  border: 2px solid #454b47;
  border-radius: 50%;
  box-shadow: 0 0 0 2px #2c302d;
}

.status-indicator.online {
  background: #62b88e;
}

.status-indicator.offline {
  background: #db796b;
}

.status-copy {
  flex: 1;
  gap: 2px;
}

.status-copy strong {
  color: #dde2de;
  font-size: 12px;
  font-weight: 550;
}

.status-copy small {
  color: #87918a;
  font-size: 10px;
}

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(var(--sidebar-width), calc(100vw - 52px));
    transform: translateX(-100%);
    transition: transform 190ms ease;
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .sidebar-close {
    display: grid;
  }
}
</style>
