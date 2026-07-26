<script setup lang="ts">
import { ArrowUp, CircleAlert, RotateCcw } from '@lucide/vue';
import { computed, nextTick, ref, watch } from 'vue';

import type { FailedChatRequest } from '../../types/chat';

const props = defineProps<{
  modelValue: string;
  busy: boolean;
  failure: FailedChatRequest | undefined;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
  send: [];
  retry: [];
}>();

const textarea = ref<HTMLTextAreaElement>();
const characterCount = computed(() => props.modelValue.length);
const sendDisabled = computed(() => props.busy || !props.modelValue.trim());

function updateMessage(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value);
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    emit('send');
  }
}

function focus(): void {
  textarea.value?.focus();
}

function resizeTextarea(): void {
  const element = textarea.value;
  if (element === undefined) {
    return;
  }
  element.style.height = 'auto';
  element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
}

watch(
  () => props.modelValue,
  () => void nextTick(resizeTextarea),
);

defineExpose({ focus });
</script>

<template>
  <div class="composer-region">
    <div v-if="failure" class="request-error" role="alert">
      <CircleAlert />
      <span>{{ failure.description }}</span>
      <button type="button" @click="emit('retry')"><RotateCcw /><span>重试</span></button>
    </div>
    <form class="composer-form" @submit.prevent="emit('send')">
      <textarea
        ref="textarea"
        :value="modelValue"
        rows="1"
        maxlength="16000"
        aria-label="输入消息"
        placeholder="给 Stargazer 发送消息"
        :disabled="busy"
        @input="updateMessage"
        @keydown="handleKeydown"
      ></textarea>
      <div class="composer-actions">
        <span class="character-count" aria-live="polite">
          {{ characterCount >= 12000 ? `${characterCount} / 16000` : '' }}
        </span>
        <button
          class="send-button"
          type="submit"
          aria-label="发送消息"
          title="发送消息"
          :disabled="sendDisabled"
        >
          <ArrowUp />
        </button>
      </div>
    </form>
    <p class="composer-note">Stargazer 可能会出错，请核对重要信息。</p>
  </div>
</template>

<style scoped>
.composer-region {
  position: relative;
  z-index: 8;
  padding: 10px max(20px, calc((100% - 820px) / 2)) 14px;
  background: var(--page);
}

.composer-form {
  display: flex;
  min-height: 58px;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 10px 10px 15px;
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  box-shadow: 0 8px 26px rgb(28 33 30 / 8%);
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease;
}

.composer-form:focus-within {
  border-color: #7fa891;
  box-shadow:
    0 0 0 3px rgb(50 112 90 / 10%),
    0 8px 26px rgb(28 33 30 / 8%);
}

.composer-form textarea {
  min-width: 0;
  min-height: 36px;
  max-height: 180px;
  flex: 1;
  padding: 8px 0 5px;
  resize: none;
  overflow-y: auto;
  color: var(--ink);
  font-size: 14px;
  line-height: 1.55;
  background: transparent;
  border: 0;
  outline: 0;
  scrollbar-color: #c6ccc7 transparent;
  scrollbar-width: thin;
}

.composer-form textarea::placeholder {
  color: var(--ink-faint);
}

.composer-actions {
  display: flex;
  min-width: 38px;
  min-height: 36px;
  align-items: center;
  gap: 8px;
}

.character-count {
  color: var(--ink-faint);
  font-size: 10px;
  white-space: nowrap;
}

.send-button {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  background: var(--accent);
  border-radius: 7px;
  transition:
    background-color 150ms ease,
    transform 150ms ease;
}

.send-button:not(:disabled):hover {
  background: var(--accent-hover);
  transform: translateY(-1px);
}

.send-button :deep(svg) {
  width: 18px;
  height: 18px;
}

.composer-note {
  margin: 7px 0 0;
  color: var(--ink-faint);
  font-size: 10px;
  text-align: center;
}

.request-error {
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  gap: 9px;
  margin-bottom: 8px;
  padding: 7px 8px 7px 11px;
  color: #7b342d;
  font-size: 12px;
  background: var(--danger-soft);
  border: 1px solid #edc9c3;
  border-radius: 7px;
}

.request-error > :deep(svg) {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
}

.request-error > span {
  min-width: 0;
  flex: 1;
  overflow-wrap: anywhere;
}

.request-error button {
  display: flex;
  height: 28px;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  color: #76352e;
  font-size: 11px;
  font-weight: 600;
  background: #fff;
  border: 1px solid #e6bbb4;
  border-radius: 5px;
}

.request-error button :deep(svg) {
  width: 13px;
  height: 13px;
}

@media (max-width: 640px) {
  .composer-region {
    padding: 8px 10px max(10px, env(safe-area-inset-bottom));
  }

  .composer-form {
    min-height: 54px;
    padding: 8px 8px 8px 12px;
  }

  .composer-note {
    margin-top: 5px;
  }
}
</style>
