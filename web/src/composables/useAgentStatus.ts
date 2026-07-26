import { onMounted, onUnmounted, ref } from 'vue';

import { loadAgentStatus } from '../services/chat-api';
import type { AgentStatus, AgentViewStatus } from '../types/chat';

export function useAgentStatus() {
  const status = ref<AgentViewStatus>({
    state: 'loading',
    label: '正在连接',
    model: 'Stargazer Agent',
  });
  const agentStatus = ref<AgentStatus>();
  let requestVersion = 0;

  async function refreshStatus(): Promise<void> {
    const currentVersion = ++requestVersion;
    try {
      const response = await loadAgentStatus();
      if (currentVersion !== requestVersion) {
        return;
      }
      agentStatus.value = response;
      status.value = {
        state: 'online',
        label: 'Agent 已就绪',
        model: `${response.model} · ${response.conversationStorage === 'sqlite' ? 'SQLite 记忆' : '会话内存'}`,
      };
    } catch {
      if (currentVersion !== requestVersion) {
        return;
      }
      agentStatus.value = undefined;
      status.value = {
        state: 'offline',
        label: '连接不可用',
        model: '请检查服务状态',
      };
    }
  }

  onMounted(() => void refreshStatus());
  onUnmounted(() => {
    requestVersion += 1;
  });

  return { status, agentStatus, refreshStatus };
}
