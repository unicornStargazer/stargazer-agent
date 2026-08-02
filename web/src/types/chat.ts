export type ConversationRole = 'user' | 'assistant';

export interface TokenUsage {
  readonly inputTokens?: number | undefined;
  readonly outputTokens?: number | undefined;
  readonly reasoningTokens?: number | undefined;
  readonly totalTokens?: number | undefined;
}

export interface ConversationMessage {
  readonly id: string;
  readonly role: ConversationRole;
  readonly content: string;
  readonly requestId?: string | undefined;
  readonly reasoning?: string | undefined;
  readonly usage?: TokenUsage | undefined;
}

export interface Conversation {
  readonly id: string;
  profileId: string;
  title: string;
  readonly createdAt: string;
  updatedAt: string;
  readonly messages: ConversationMessage[];
}

export interface PendingChatRequest {
  readonly requestId: string;
  readonly message: string;
}

export interface FailedChatRequest extends PendingChatRequest {
  readonly description: string;
}

export interface AgentStatus {
  readonly ready: boolean;
  readonly model: string;
  readonly conversationStorage: 'memory' | 'sqlite';
  readonly defaultProfile?: AgentProfile | undefined;
}

export interface AgentProfile {
  readonly id: string;
  readonly name: string;
  readonly model: string;
}

export interface AgentViewStatus {
  readonly state: 'loading' | 'online' | 'offline';
  readonly label: string;
  readonly model: string;
}

export interface ApiChatMessage {
  readonly role: 'assistant';
  readonly content: string;
}

export interface ApiConversationMessage {
  readonly role: ConversationRole;
  readonly content: string;
  readonly reasoning?: string | undefined;
  readonly usage?: TokenUsage | undefined;
}

export type ProfileLoadState = 'loading' | 'ready' | 'empty' | 'error';

export interface ChatRequest {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string;
}
