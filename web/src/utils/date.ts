export function formatConversationTime(value: string): string {
  const date = new Date(value);
  const now = new Date();
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' });
}
