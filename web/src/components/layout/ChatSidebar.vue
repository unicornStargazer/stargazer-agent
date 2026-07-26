<script setup lang="ts">
import {
  ChevronsUpDown,
  MessageSquare,
  PanelLeftClose,
  Sparkles,
  SquarePen,
  Trash2,
} from '@lucide/vue';

import type { AgentViewStatus, Conversation } from '../../types/chat';
import { formatConversationTime } from '../../utils/date';

const props = defineProps<{
  conversations: readonly Conversation[];
  activeConversationId: string | undefined;
  pendingConversationIds: readonly string[];
  deletingConversationIds: readonly string[];
  status: AgentViewStatus;
}>();

const emit = defineEmits<{
  close: [];
  create: [];
  select: [conversationId: string];
  delete: [conversationId: string];
}>();

function isUnavailable(conversationId: string): boolean {
  return (
    props.pendingConversationIds.includes(conversationId) ||
    props.deletingConversationIds.includes(conversationId)
  );
}
</script>

<template>
  <aside class="sidebar" aria-label="会话导航">
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

    <nav class="conversation-navigation" aria-label="历史会话">
      <div class="section-label">最近对话</div>
      <div class="conversation-list">
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === activeConversationId }"
        >
          <button
            type="button"
            class="conversation-select"
            :aria-current="conversation.id === activeConversationId ? 'page' : undefined"
            @click="emit('select', conversation.id)"
          >
            <MessageSquare />
            <span>
              <strong>{{ conversation.title }}</strong>
              <small>{{ formatConversationTime(conversation.updatedAt) }}</small>
            </span>
          </button>
          <button
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
  margin-top: 26px;
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
  padding: 6px 36px 6px 9px;
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
  color: #89928c;
  font-size: 10px;
}

.conversation-delete {
  position: absolute;
  right: 5px;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #929b95;
  background: transparent;
  border-radius: 5px;
  opacity: 0;
}

.conversation-delete :deep(svg) {
  width: 14px;
  height: 14px;
}

.conversation-item:hover .conversation-delete,
.conversation-item.active .conversation-delete,
.conversation-delete:focus-visible {
  opacity: 1;
}

.conversation-delete:not(:disabled):hover {
  color: #ffc6bd;
  background: #51312e;
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
