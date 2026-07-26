import type { AgentTool, ToolDefinition, ToolExecutionContext } from './tool.js';
import { ToolRegistrationError } from './tool.js';

const TOOL_NAME_PATTERN = /^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/;
const MAX_TOOL_RESULT_LENGTH = 16_000;

/**
 * Holds an allow-listed set of tools. A tool must be registered by server code;
 * model output alone can never create or execute a capability.
 */
export class ToolRegistry {
  private readonly toolsByName: ReadonlyMap<string, AgentTool>;

  constructor(tools: readonly AgentTool[] = []) {
    this.toolsByName = createToolMap(tools);
  }

  definitions(): readonly ToolDefinition[] {
    return [...this.toolsByName.values()].map(({ name, description, parameters }) => ({
      name,
      description,
      parameters,
    }));
  }

  isEmpty(): boolean {
    return this.toolsByName.size === 0;
  }

  async execute(
    toolName: string,
    serializedInput: string,
    context: ToolExecutionContext,
  ): Promise<string> {
    const tool = this.toolsByName.get(toolName);
    if (tool === undefined) {
      return `Tool '${toolName}' is not available.`;
    }

    const parsedInput = parseToolInput(serializedInput);
    if (!parsedInput.valid) {
      return parsedInput.message;
    }

    try {
      return normalizeToolResult(await tool.execute(parsedInput.value, context));
    } catch {
      return `Tool '${toolName}' failed to execute.`;
    }
  }
}

function createToolMap(tools: readonly AgentTool[]): ReadonlyMap<string, AgentTool> {
  const toolsByName = new Map<string, AgentTool>();
  for (const tool of tools) {
    validateTool(tool);
    if (toolsByName.has(tool.name)) {
      throw new ToolRegistrationError(`Duplicate tool name: ${tool.name}`);
    }
    toolsByName.set(tool.name, tool);
  }
  return toolsByName;
}

function validateTool(tool: AgentTool): void {
  if (!TOOL_NAME_PATTERN.test(tool.name)) {
    throw new ToolRegistrationError(
      'Tool name must be 1-64 ASCII letters, digits, hyphens, or underscores.',
    );
  }
  if (!tool.description.trim()) {
    throw new ToolRegistrationError(`Tool '${tool.name}' must have a description.`);
  }
  if (!isRecord(tool.parameters)) {
    throw new ToolRegistrationError(`Tool '${tool.name}' parameters must be a JSON schema object.`);
  }
}

type ParsedToolInput =
  | { readonly valid: true; readonly value: unknown }
  | { readonly valid: false; readonly message: string };

function parseToolInput(serializedInput: string): ParsedToolInput {
  try {
    return { valid: true, value: JSON.parse(serializedInput) as unknown };
  } catch {
    return { valid: false, message: 'Tool arguments must be valid JSON.' };
  }
}

function normalizeToolResult(result: string): string {
  if (typeof result !== 'string') {
    return 'Tool returned an invalid result.';
  }
  const normalizedResult = result.trim();
  if (!normalizedResult) {
    return 'Tool completed without a result.';
  }
  return normalizedResult.slice(0, MAX_TOOL_RESULT_LENGTH);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
