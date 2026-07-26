import { onMounted, onUnmounted, ref } from 'vue';

import { loadAgentProfiles } from '../services/chat-api';
import type { AgentProfile, ProfileLoadState } from '../types/chat';

export function useAgentProfiles() {
  const profiles = ref<readonly AgentProfile[]>([]);
  const state = ref<ProfileLoadState>('loading');
  const error = ref<string>();
  let requestVersion = 0;

  async function refreshProfiles(): Promise<void> {
    const currentVersion = ++requestVersion;
    state.value = 'loading';
    error.value = undefined;
    try {
      const loadedProfiles = await loadAgentProfiles();
      if (currentVersion !== requestVersion) {
        return;
      }
      profiles.value = loadedProfiles;
      state.value = loadedProfiles.length === 0 ? 'empty' : 'ready';
    } catch (requestError: unknown) {
      if (currentVersion !== requestVersion) {
        return;
      }
      profiles.value = [];
      state.value = 'error';
      error.value =
        requestError instanceof Error && requestError.message
          ? requestError.message
          : 'Agent Profile 加载失败';
    }
  }

  onMounted(() => void refreshProfiles());
  onUnmounted(() => {
    requestVersion += 1;
  });

  return { profiles, state, error, refreshProfiles };
}
