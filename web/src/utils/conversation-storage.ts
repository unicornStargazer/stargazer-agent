import type { Conversation, ConversationMessage } from '../types/chat';

export const WORKSPACE_STORAGE_KEY = 'stargazer.chat.workspace.v1';
export const ACTIVE_CONVERSATION_STORAGE_KEY = 'stargazer.chat.active.v1';

const MAX_STORED_CONVERSATIONS = 50;

export interface StoredWorkspace {
  readonly conversations: Conversation[];
  readonly activeConversationId: string | undefined;
}

export function loadWorkspace(): StoredWorkspace {
  const conversations = parseStoredConversations(
    window.localStorage.getItem(WORKSPACE_STORAGE_KEY),
  );
  const activeConversationId = window.localStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY);
  return {
    conversations,
    activeConversationId: activeConversationId || undefined,
  };
}

export function saveWorkspace(workspace: StoredWorkspace): void {
  window.localStorage.setItem(
    WORKSPACE_STORAGE_KEY,
    JSON.stringify(workspace.conversations.slice(0, MAX_STORED_CONVERSATIONS)),
  );
  window.localStorage.setItem(
    ACTIVE_CONVERSATION_STORAGE_KEY,
    workspace.activeConversationId ?? '',
  );
}

function parseStoredConversations(value: string | null): Conversation[] {
  if (value === null) {
    return [];
  }
  try {
    const parsedValue = JSON.parse(value) as unknown;
    if (!Array.isArray(parsedValue)) {
      return [];
    }
    return parsedValue
      .filter(isStoredConversation)
      .slice(0, MAX_STORED_CONVERSATIONS)
      .map(cloneConversation);
  } catch {
    return [];
  }
}

function isStoredConversation(value: unknown): value is Conversation {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    typeof value.createdAt === 'string' &&
    typeof value.updatedAt === 'string' &&
    Array.isArray(value.messages) &&
    value.messages.every(isStoredMessage)
  );
}

function isStoredMessage(value: unknown): value is ConversationMessage {
  if (!isRecord(value)) {
    return false;
  }
  const requestIdValid = value.requestId === undefined || typeof value.requestId === 'string';
  return (
    typeof value.id === 'string' &&
    (value.role === 'user' || value.role === 'assistant') &&
    typeof value.content === 'string' &&
    requestIdValid
  );
}

function cloneConversation(conversation: Conversation): Conversation {
  return {
    id: conversation.id,
    title: conversation.title,
    createdAt: conversation.createdAt,
    updatedAt: conversation.updatedAt,
    messages: conversation.messages.map((message) => ({ ...message })),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
