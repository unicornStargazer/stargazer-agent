<script setup lang="ts">
import { computed } from 'vue';

import { renderMarkdown } from '../../utils/markdown';

const props = defineProps<{
  content: string;
}>();

const renderedContent = computed(() => renderMarkdown(props.content));
</script>

<template>
  <!-- 内容已经由 DOMPurify 消毒。 -->
  <!-- eslint-disable-next-line vue/no-v-html -->
  <div class="markdown-body" v-html="renderedContent"></div>
</template>

<style scoped>
.markdown-body {
  color: #29312c;
  font-size: 14px;
  line-height: 1.72;
  overflow-wrap: anywhere;
}

.markdown-body :deep(> :first-child) {
  margin-top: 0;
}

.markdown-body :deep(> :last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(blockquote) {
  margin: 0 0 13px;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 22px 0 10px;
  color: #202622;
  font-weight: 650;
  line-height: 1.35;
  letter-spacing: 0;
}

.markdown-body :deep(h1) {
  font-size: 20px;
}

.markdown-body :deep(h2) {
  font-size: 17px;
}

.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  font-size: 15px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 22px;
}

.markdown-body :deep(li + li) {
  margin-top: 5px;
}

.markdown-body :deep(a) {
  color: var(--accent);
  text-underline-offset: 3px;
}

.markdown-body :deep(blockquote) {
  padding: 2px 0 2px 14px;
  color: var(--ink-muted);
  border-left: 3px solid #b7cabf;
}

.markdown-body :deep(:not(pre) > code) {
  padding: 2px 5px;
  color: #8b4033;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 0.9em;
  background: #f1ece9;
  border: 1px solid #e6dcd7;
  border-radius: 4px;
}

.markdown-body :deep(.code-block) {
  margin: 14px 0;
  overflow: hidden;
  background: #202421;
  border: 1px solid #303632;
  border-radius: 7px;
}

.markdown-body :deep(.code-header) {
  display: flex;
  height: 36px;
  align-items: center;
  padding: 0 13px;
  color: #aeb7b1;
  font-size: 10px;
  text-transform: uppercase;
  background: #282d29;
  border-bottom: 1px solid #373d39;
}

.markdown-body :deep(.code-block pre) {
  max-width: 100%;
  margin: 0;
  padding: 16px;
  overflow: auto;
  color: #e5eae7;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  tab-size: 2;
}
</style>
