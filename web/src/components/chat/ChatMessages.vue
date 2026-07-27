<script setup lang="ts">
import { Brain, Check, Copy, Sparkles } from '@lucide/vue';
import { computed, onUnmounted, ref } from 'vue';

import type { ConversationMessage } from '../../types/chat';
import MarkdownContent from './MarkdownContent.vue';

const props = defineProps<{
  messages: readonly ConversationMessage[];
  busy: boolean;
}>();

/** 空助手消息是流生成前的内部占位，不应作为独立消息渲染。 */
const visibleMessages = computed(() =>
  props.messages.filter(
    (message) => message.role === 'user' || message.content || message.reasoning,
  ),
);
const streamingMessageId = computed(() => {
  if (!props.busy) {
    return undefined;
  }
  const lastMessage = visibleMessages.value.at(-1);
  return lastMessage?.role === 'assistant' && lastMessage.content ? lastMessage.id : undefined;
});
const showTypingIndicator = computed(() => props.busy && streamingMessageId.value === undefined);

const copiedMessageId = ref<string | undefined>();
let copyResetTimeout: number | undefined;

async function copyMessage(message: ConversationMessage): Promise<void> {
  try {
    await navigator.clipboard.writeText(message.content);
    copiedMessageId.value = message.id;
    window.clearTimeout(copyResetTimeout);
    copyResetTimeout = window.setTimeout(() => {
      copiedMessageId.value = undefined;
    }, 1400);
  } catch {
    copiedMessageId.value = undefined;
  }
}

onUnmounted(() => window.clearTimeout(copyResetTimeout));

function formatUsage(message: ConversationMessage): string | undefined {
  const usage = message.usage;
  if (usage === undefined) {
    return undefined;
  }
  const values = [
    usage.inputTokens === undefined ? undefined : `输入 ${String(usage.inputTokens)}`,
    usage.outputTokens === undefined ? undefined : `输出 ${String(usage.outputTokens)}`,
    usage.reasoningTokens === undefined ? undefined : `思考 ${String(usage.reasoningTokens)}`,
    usage.totalTokens === undefined ? undefined : `共 ${String(usage.totalTokens)}`,
  ].filter((value): value is string => value !== undefined);
  return values.length === 0 ? undefined : `${values.join(' · ')} Tokens`;
}
</script>

<template>
  <div class="message-list" aria-live="polite">
    <article
      v-for="message in visibleMessages"
      :key="message.id"
      class="chat-message"
      :class="`${message.role}-message`"
    >
      <div v-if="message.role === 'user'" class="user-bubble">{{ message.content }}</div>
      <template v-else>
        <div class="assistant-avatar" aria-hidden="true"><Sparkles /></div>
        <div class="assistant-response">
          <details
            v-if="message.reasoning"
            class="reasoning-panel"
            :open="message.id === streamingMessageId"
          >
            <summary><Brain aria-hidden="true" /><span>思考过程</span></summary>
            <pre>{{ message.reasoning }}</pre>
          </details>
          <MarkdownContent v-if="message.content" :content="message.content" />
          <span
            v-if="message.id === streamingMessageId"
            class="stream-cursor"
            aria-hidden="true"
          ></span>
          <div v-if="formatUsage(message)" class="token-usage">{{ formatUsage(message) }}</div>
          <div v-else class="message-actions">
            <button
              class="copy-button"
              type="button"
              aria-label="复制回复"
              title="复制回复"
              @click="copyMessage(message)"
            >
              <Check v-if="copiedMessageId === message.id" />
              <Copy v-else />
            </button>
          </div>
        </div>
      </template>
    </article>

    <article
      v-if="showTypingIndicator"
      class="chat-message assistant-message typing-message"
      aria-label="Stargazer 正在生成回复"
    >
      <div class="assistant-avatar" aria-hidden="true"><Sparkles /></div>
      <div class="typing-indicator"><span></span><span></span><span></span></div>
    </article>
  </div>
</template>

<style scoped>
.message-list {
  width: min(820px, calc(100% - 40px));
  margin: 0 auto;
  padding: 44px 0 34px;
}

.chat-message {
  display: flex;
  width: 100%;
  margin-bottom: 30px;
}

.user-message {
  justify-content: flex-end;
}

.user-bubble {
  max-width: min(78%, 620px);
  padding: 11px 15px;
  color: #243029;
  font-size: 14px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  background: #e8ede9;
  border: 1px solid #d9e0da;
  border-radius: 8px 8px 2px;
}

.assistant-message {
  align-items: flex-start;
  gap: 13px;
}

.assistant-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid #cfe1d7;
  border-radius: 7px;
}

.assistant-avatar :deep(svg) {
  width: 16px;
  height: 16px;
}

.assistant-response {
  min-width: 0;
  flex: 1;
  padding-top: 3px;
}

.reasoning-panel {
  margin: 0 0 12px;
  overflow: hidden;
  border: 1px solid #d9e0da;
  border-radius: 6px;
}

.reasoning-panel summary {
  display: flex;
  height: 30px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  color: var(--ink-muted);
  font-size: 11px;
  cursor: pointer;
  background: var(--surface-strong);
}

.reasoning-panel summary :deep(svg) {
  width: 14px;
  height: 14px;
}

.reasoning-panel pre {
  max-height: 220px;
  margin: 0;
  padding: 9px;
  overflow: auto;
  color: var(--ink-muted);
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.token-usage {
  margin-top: 9px;
  color: var(--ink-faint);
  font-size: 11px;
}

.stream-cursor {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin: 4px 0 0 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  animation: stream-cursor 850ms steps(1) infinite;
}

.message-actions {
  display: flex;
  min-height: 30px;
  align-items: center;
  margin-top: 8px;
  opacity: 0;
  transition: opacity 150ms ease;
}

.assistant-message:hover .message-actions,
.message-actions:focus-within {
  opacity: 1;
}

.copy-button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: var(--ink-faint);
  background: transparent;
  border-radius: 5px;
}

.copy-button:hover {
  color: var(--ink);
  background: var(--surface-strong);
}

.copy-button :deep(svg) {
  width: 15px;
  height: 15px;
}

.typing-message {
  min-height: 40px;
}

.typing-indicator {
  display: flex;
  height: 30px;
  align-items: center;
  gap: 5px;
}

.typing-indicator span {
  width: 5px;
  height: 5px;
  background: #849087;
  border-radius: 50%;
  animation: typing 1.1s ease-in-out infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 120ms;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 240ms;
}

@keyframes typing {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.42;
  }

  30% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

@keyframes stream-cursor {
  0%,
  48% {
    opacity: 1;
  }

  49%,
  100% {
    opacity: 0;
  }
}

@media (max-width: 640px) {
  .message-list {
    width: calc(100% - 28px);
    padding: 28px 0 20px;
  }

  .chat-message {
    margin-bottom: 24px;
  }

  .user-bubble {
    max-width: 88%;
  }

  .assistant-message {
    gap: 10px;
  }

  .assistant-avatar {
    width: 28px;
    height: 28px;
  }

  .message-actions {
    opacity: 1;
  }
}
</style>
