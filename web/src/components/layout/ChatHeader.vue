<script setup lang="ts">
import { Download, PanelLeft, Trash2 } from '@lucide/vue';

import type { AgentProfile, ProfileLoadState } from '../../types/chat';
import AgentProfileMenu from './AgentProfileMenu.vue';

defineProps<{
  title: string;
  busy: boolean;
  deleting: boolean;
  profiles: readonly AgentProfile[];
  selectedProfileId: string;
  profileState: ProfileLoadState;
  profileError: string | undefined;
  exportDisabled: boolean;
}>();

const emit = defineEmits<{
  openSidebar: [];
  delete: [];
  export: [];
  selectProfile: [profileId: string];
  retryProfiles: [];
}>();
</script>

<template>
  <header class="topbar">
    <button
      class="icon-button mobile-menu-button"
      type="button"
      aria-label="打开会话导航"
      title="打开会话导航"
      @click="emit('openSidebar')"
    >
      <PanelLeft />
    </button>
    <div class="conversation-heading">
      <strong>{{ title }}</strong>
      <span>{{ busy ? '正在生成回复' : '随时可以开始' }}</span>
    </div>
    <AgentProfileMenu
      :profiles="profiles"
      :selected-profile-id="selectedProfileId"
      :state="profileState"
      :error="profileError"
      :disabled="busy"
      @select="emit('selectProfile', $event)"
      @retry="emit('retryProfiles')"
    />
    <button
      class="icon-button"
      type="button"
      aria-label="导出当前对话"
      title="导出当前对话"
      :disabled="exportDisabled"
      @click="emit('export')"
    >
      <Download />
    </button>
    <button
      class="icon-button"
      type="button"
      aria-label="删除当前对话"
      title="删除当前对话"
      :disabled="busy || deleting"
      @click="emit('delete')"
    >
      <Trash2 />
    </button>
  </header>
</template>

<style scoped>
.topbar {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 22px;
  background: rgb(247 248 246 / 94%);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}

.conversation-heading {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
  text-align: center;
}

.conversation-heading strong,
.conversation-heading span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-heading strong {
  font-size: 14px;
  font-weight: 650;
}

.conversation-heading span {
  color: var(--ink-faint);
  font-size: 10px;
}

.mobile-menu-button {
  visibility: hidden;
}

@media (max-width: 900px) {
  .topbar {
    padding: 0 14px;
  }

  .mobile-menu-button {
    visibility: visible;
  }
}

@media (max-width: 640px) {
  .topbar {
    padding: 0 10px;
  }

  .conversation-heading {
    text-align: left;
  }

  .conversation-heading span {
    display: none;
  }
}
</style>
