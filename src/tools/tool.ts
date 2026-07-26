/** A server-side capability that an agent may invoke during one chat turn. */
export interface AgentTool {
  readonly name: string;
  readonly description: string;
  readonly parameters: Record<string, unknown>;
  execute(input: unknown, context: ToolExecutionContext): Promise<string>;
}

/** Context deliberately excludes credentials and HTTP request objects. */
export interface ToolExecutionContext {
  readonly sessionId: string;
}

export interface ToolDefinition {
  readonly name: string;
  readonly description: string;
  readonly parameters: Record<string, unknown>;
}

export class ToolRegistrationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ToolRegistrationError';
  }
}
