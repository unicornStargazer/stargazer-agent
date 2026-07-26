export function createIdentifier(prefix: string): string {
  const value = window.crypto.randomUUID();
  return `${prefix}-${value}`;
}
