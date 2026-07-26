<script setup lang="ts">
import { ArrowUpRight, Code2, Lightbulb, Route, Sparkles, TextCursorInput } from '@lucide/vue';

const emit = defineEmits<{
  choose: [prompt: string];
}>();

const suggestions = [
  {
    title: '分析问题',
    description: '梳理思路与下一步',
    prompt: '帮我分析这个问题，并给出清晰的解决步骤',
    tone: 'sage',
    icon: Route,
  },
  {
    title: '审查代码',
    description: '定位风险与改进点',
    prompt: '帮我审查一段代码，重点检查潜在缺陷和可维护性',
    tone: 'amber',
    icon: Code2,
  },
  {
    title: '润色文字',
    description: '调整表达与结构',
    prompt: '帮我把这段文字改写得更准确、简洁、有条理',
    tone: 'coral',
    icon: TextCursorInput,
  },
  {
    title: '拓展创意',
    description: '探索不同可行方向',
    prompt: '围绕我的目标提供三个不同方向的创意方案',
    tone: 'steel',
    icon: Lightbulb,
  },
] as const;
</script>

<template>
  <div class="empty-state">
    <div class="empty-mark" aria-hidden="true"><Sparkles /></div>
    <div class="empty-copy">
      <p class="eyebrow">STARGAZER AGENT</p>
      <h1>今天想一起完成什么？</h1>
    </div>
    <div class="suggestion-grid" aria-label="建议问题">
      <button
        v-for="suggestion in suggestions"
        :key="suggestion.prompt"
        class="suggestion-button"
        type="button"
        @click="emit('choose', suggestion.prompt)"
      >
        <span class="suggestion-icon" :class="suggestion.tone">
          <component :is="suggestion.icon" />
        </span>
        <span>
          <strong>{{ suggestion.title }}</strong>
          <small>{{ suggestion.description }}</small>
        </span>
        <ArrowUpRight />
      </button>
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  width: min(760px, calc(100% - 40px));
  min-height: 100%;
  flex-direction: column;
  justify-content: center;
  margin: 0 auto;
  padding: 48px 0 68px;
}

.empty-mark {
  display: grid;
  width: 44px;
  height: 44px;
  margin-bottom: 20px;
  place-items: center;
  color: #f4f7f5;
  background: var(--accent);
  border-radius: 8px;
  box-shadow: 0 6px 16px rgb(50 112 90 / 20%);
}

.empty-mark :deep(svg) {
  width: 22px;
  height: 22px;
}

.empty-copy {
  margin-bottom: 30px;
}

.eyebrow {
  margin: 0 0 7px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0;
}

.empty-copy h1 {
  max-width: 620px;
  margin: 0;
  color: #202622;
  font-size: 30px;
  font-weight: 620;
  line-height: 1.25;
  letter-spacing: 0;
}

.suggestion-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.suggestion-button {
  display: grid;
  min-width: 0;
  min-height: 82px;
  grid-template-columns: 38px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 12px;
  padding: 13px;
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 1px 1px rgb(28 33 30 / 2%);
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease,
    transform 150ms ease;
}

.suggestion-button:hover {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-soft);
  transform: translateY(-1px);
}

.suggestion-button > span:nth-child(2) {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.suggestion-button strong,
.suggestion-button small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suggestion-button strong {
  font-size: 13px;
  font-weight: 650;
}

.suggestion-button small {
  color: var(--ink-muted);
  font-size: 11px;
}

.suggestion-button > :deep(svg) {
  width: 16px;
  height: 16px;
  color: var(--ink-faint);
}

.suggestion-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 7px;
}

.suggestion-icon :deep(svg) {
  width: 18px;
  height: 18px;
}

.suggestion-icon.sage {
  color: var(--accent);
  background: var(--accent-soft);
}

.suggestion-icon.amber {
  color: var(--amber);
  background: var(--amber-soft);
}

.suggestion-icon.coral {
  color: var(--coral);
  background: var(--coral-soft);
}

.suggestion-icon.steel {
  color: var(--steel);
  background: var(--steel-soft);
}

@media (max-width: 640px) {
  .empty-state {
    width: min(calc(100% - 28px), 520px);
    justify-content: flex-start;
    padding: 15vh 0 42px;
  }

  .empty-mark {
    width: 40px;
    height: 40px;
    margin-bottom: 16px;
  }

  .empty-copy {
    margin-bottom: 24px;
  }

  .empty-copy h1 {
    font-size: 24px;
  }

  .suggestion-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .suggestion-button {
    min-height: 68px;
    grid-template-columns: 34px minmax(0, 1fr) 16px;
    gap: 10px;
    padding: 10px 11px;
  }

  .suggestion-icon {
    width: 34px;
    height: 34px;
  }
}

@media (max-height: 680px) and (max-width: 640px) {
  .empty-state {
    padding-top: 32px;
  }

  .empty-copy {
    margin-bottom: 18px;
  }

  .suggestion-button {
    min-height: 58px;
  }

  .suggestion-button small {
    display: none;
  }
}
</style>
