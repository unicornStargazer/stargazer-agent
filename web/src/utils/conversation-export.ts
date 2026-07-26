import type { AgentProfile, Conversation } from '../types/chat';

export function createConversationMarkdown(
  conversation: Conversation,
  profile: AgentProfile | undefined,
): string {
  const lines = [
    `# ${conversation.title}`,
    '',
    `> Agent: ${profile?.name ?? conversation.profileId}`,
    `> Model: ${profile?.model ?? '未知'}`,
    '',
  ];
  for (const message of conversation.messages) {
    if (!message.content) {
      continue;
    }
    lines.push(`## ${message.role === 'user' ? '用户' : (profile?.name ?? 'Stargazer')}`);
    lines.push('', message.content, '');
  }
  return `${lines.join('\n').trimEnd()}\n`;
}

export function createConversationFilename(title: string): string {
  const titleWithoutControlCharacters = [...title.normalize('NFKC')]
    .map((character) => (character.charCodeAt(0) < 32 ? '-' : character))
    .join('');
  const normalizedTitle = titleWithoutControlCharacters
    .replace(/[<>:"/\\|?*]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
  return `${normalizedTitle || 'conversation'}.md`;
}

export function downloadConversationMarkdown(
  conversation: Conversation,
  profile: AgentProfile | undefined,
): void {
  const objectUrl = URL.createObjectURL(
    new Blob([createConversationMarkdown(conversation, profile)], {
      type: 'text/markdown;charset=utf-8',
    }),
  );
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = createConversationFilename(conversation.title);
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}
