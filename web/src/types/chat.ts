export type ConversationRole = 'user' | 'assistant';

export interface ConversationMessage {
  readonly id: string;
  readonly role: ConversationRole;
  readonly content: string;
  readonly requestId?: string | undefined;
}

export interface Conversation {
  readonly id: string;
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
  readonly conversationStorage: 'memory';
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

export interface ChatRequest {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
}
