import { onMounted, ref } from 'vue';

import { loadAgentStatus } from '../services/chat-api';
import type { AgentViewStatus } from '../types/chat';

export function useAgentStatus() {
  const status = ref<AgentViewStatus>({
    state: 'loading',
    label: '正在连接',
    model: 'Stargazer Agent',
  });

  async function refreshStatus(): Promise<void> {
    try {
      const response = await loadAgentStatus();
      status.value = {
        state: 'online',
        label: 'Agent 已就绪',
        model: response.model,
      };
    } catch {
      status.value = {
        state: 'offline',
        label: '连接不可用',
        model: '请检查服务状态',
      };
    }
  }

  onMounted(() => void refreshStatus());

  return { status, refreshStatus };
}
