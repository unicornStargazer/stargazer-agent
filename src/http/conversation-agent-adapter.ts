/** 将运行时 Agent 适配为应用层会话契约，HTTP 层不直接编排 Profile。 */

import type { ConversationAgent } from '../application/conversation-service.js';
import type { ModelStreamEvent } from '../chat/index.js';
import type { AgentHttpAppOptions } from './types.js';

export function createConversationAgent(options: AgentHttpAppOptions): ConversationAgent {
  return {
    chat: (sessionId, profileId, message) =>
      options.profileAgent?.chat(sessionId, profileId, message) ??
      options.agent.chat(sessionId, message),
    chatStream: streamConversation,
    clearHistory: (sessionId) => options.agent.clearHistory(sessionId),
  };

  async function* streamConversation(
    sessionId: string,
    profileId: string | undefined,
    message: string,
  ): AsyncGenerator<ModelStreamEvent> {
    if (options.profileAgent !== undefined) {
      yield* options.profileAgent.chatStream(sessionId, profileId, message);
      return;
    }
    const response = await options.agent.chat(sessionId, message);
    yield { type: 'content', content: response.content };
  }
}
