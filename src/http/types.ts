/** HTTP 适配层对运行时依赖的最小抽象，不依赖具体模型或存储实现。 */

import type { ChatMessage } from '../chat/index.js';
import type { ProfileAgent } from '../profiles/index.js';

export type ConversationStorageKind = 'memory' | 'sqlite';

export interface WebAgent {
  chat(sessionId: string, text: string): Promise<ChatMessage>;
  history(sessionId: string): Promise<readonly ChatMessage[]>;
  clearHistory(sessionId: string): Promise<void>;
}

export interface AgentHttpAppOptions {
  readonly agent: WebAgent;
  readonly profileAgent?: ProfileAgent | undefined;
  readonly modelName?: string | undefined;
  readonly publicDirectory?: string | undefined;
  readonly conversationStorage?: ConversationStorageKind | undefined;
}
