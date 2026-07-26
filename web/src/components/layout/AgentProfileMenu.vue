<script setup lang="ts">
import { Bot, Check, ChevronDown, RotateCcw } from '@lucide/vue';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

import type { AgentProfile, ProfileLoadState } from '../../types/chat';

const props = defineProps<{
  profiles: readonly AgentProfile[];
  selectedProfileId: string;
  state: ProfileLoadState;
  error: string | undefined;
  disabled: boolean;
}>();

const emit = defineEmits<{
  select: [profileId: string];
  retry: [];
}>();

const root = ref<HTMLElement>();
const open = ref(false);
const selectedProfile = computed(() =>
  props.profiles.find((profile) => profile.id === props.selectedProfileId),
);
const menuAvailable = computed(
  () => props.state === 'error' || props.state === 'empty' || props.profiles.length > 1,
);
const triggerLabel = computed(() => {
  if (props.state === 'loading') {
    return '正在加载 Agent';
  }
  if (props.state === 'error') {
    return 'Agent 加载失败';
  }
  return selectedProfile.value?.name ?? '选择 Agent';
});

function toggleMenu(): void {
  if (!props.disabled && menuAvailable.value) {
    open.value = !open.value;
  }
}

function selectProfile(profileId: string): void {
  emit('select', profileId);
  open.value = false;
}

function retryProfiles(): void {
  open.value = false;
  emit('retry');
}

function handlePointerDown(event: PointerEvent): void {
  if (event.target instanceof Node && !root.value?.contains(event.target)) {
    open.value = false;
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    open.value = false;
  }
}

watch(
  () => props.selectedProfileId,
  () => {
    open.value = false;
  },
);

watch(menuAvailable, (available) => {
  if (!available) {
    open.value = false;
  }
});

onMounted(() => {
  document.addEventListener('pointerdown', handlePointerDown);
  document.addEventListener('keydown', handleKeydown);
});

onUnmounted(() => {
  document.removeEventListener('pointerdown', handlePointerDown);
  document.removeEventListener('keydown', handleKeydown);
});
</script>

<template>
  <div ref="root" class="profile-menu">
    <button
      class="profile-trigger"
      :class="{ selectable: menuAvailable }"
      type="button"
      :aria-haspopup="menuAvailable ? 'menu' : undefined"
      :aria-expanded="menuAvailable ? open : undefined"
      :aria-label="triggerLabel"
      :title="selectedProfile ? `${selectedProfile.name} · ${selectedProfile.model}` : triggerLabel"
      :disabled="disabled || state === 'loading'"
      @click="toggleMenu"
    >
      <Bot class="profile-icon" />
      <span>
        <strong>{{ triggerLabel }}</strong>
        <small v-if="selectedProfile">{{ selectedProfile.model }}</small>
      </span>
      <ChevronDown v-if="menuAvailable" class="profile-chevron" />
    </button>

    <div v-if="open" class="profile-popover">
      <div v-if="state === 'error'" class="profile-error" role="alert">
        <span>{{ error ?? 'Agent Profile 加载失败' }}</span>
        <button type="button" @click="retryProfiles"><RotateCcw />重试</button>
      </div>
      <div v-else-if="state === 'empty'" class="profile-empty">没有可用的 Agent</div>
      <div v-else class="profile-options" role="menu" aria-label="Agent Profile">
        <button
          v-for="profile in profiles"
          :key="profile.id"
          type="button"
          role="menuitemradio"
          :aria-checked="profile.id === selectedProfileId"
          @click="selectProfile(profile.id)"
        >
          <span>
            <strong>{{ profile.name }}</strong>
            <small>{{ profile.model }}</small>
          </span>
          <Check v-if="profile.id === selectedProfileId" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-menu {
  position: relative;
  flex: 0 0 auto;
}

.profile-trigger {
  display: grid;
  min-width: 148px;
  max-width: 200px;
  min-height: 38px;
  grid-template-columns: 17px minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  color: var(--ink);
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
}

.profile-trigger.selectable {
  grid-template-columns: 17px minmax(0, 1fr) 14px;
}

.profile-trigger:hover:not(:disabled) {
  background: var(--surface-subtle);
  border-color: var(--line-strong);
}

.profile-icon {
  width: 16px;
  height: 16px;
  color: var(--accent);
}

.profile-chevron {
  width: 13px;
  height: 13px;
  color: var(--ink-faint);
}

.profile-trigger > span,
.profile-options button > span {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.profile-trigger strong,
.profile-trigger small,
.profile-options strong,
.profile-options small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-trigger strong,
.profile-options strong {
  font-size: 11px;
  font-weight: 650;
}

.profile-trigger small,
.profile-options small {
  color: var(--ink-faint);
  font-size: 9px;
}

.profile-popover {
  position: absolute;
  z-index: 40;
  top: calc(100% + 7px);
  right: 0;
  width: min(260px, calc(100vw - 24px));
  padding: 6px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  box-shadow: var(--shadow-soft);
}

.profile-options {
  display: grid;
  gap: 2px;
}

.profile-options button {
  display: grid;
  min-height: 46px;
  grid-template-columns: minmax(0, 1fr) 16px;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  color: var(--ink);
  text-align: left;
  background: transparent;
  border-radius: 5px;
}

.profile-options button:hover,
.profile-options button[aria-checked='true'] {
  background: var(--surface-subtle);
}

.profile-options button > svg {
  width: 15px;
  height: 15px;
  color: var(--accent);
}

.profile-error,
.profile-empty {
  padding: 9px;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.5;
}

.profile-error {
  display: grid;
  gap: 8px;
}

.profile-error button {
  display: flex;
  min-height: 30px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 650;
  background: var(--accent-soft);
  border-radius: 5px;
}

.profile-error button svg {
  width: 13px;
  height: 13px;
}

@media (max-width: 640px) {
  .profile-trigger {
    display: grid;
    width: 36px;
    min-width: 36px;
    min-height: 36px;
    grid-template-columns: 1fr;
    place-items: center;
    padding: 0;
  }

  .profile-trigger > span,
  .profile-chevron {
    display: none;
  }
}
</style>
