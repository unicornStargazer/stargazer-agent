/**
 * 最小且无副作用的 Tool 示例。
 *
 * 仅用于验证模型到服务端 ToolRegistry 的调用链，不能作为文件、网络或命令能力的替代品。
 */
import type { AgentTool } from '../tool.js';

const MAXIMUM_TEXT_LENGTH = 1_000;

export const echoTextTool: AgentTool = {
  name: 'echo_text',
  description: 'Returns the supplied text unchanged. Use only when the user explicitly asks to verify a tool call.',
  parameters: {
    type: 'object',
    additionalProperties: false,
    required: ['text'],
    properties: {
      text: { type: 'string', minLength: 1, maxLength: MAXIMUM_TEXT_LENGTH },
    },
  },
  execute(input): Promise<string> {
    const validation = validateEchoText(input);
    const result = validation.valid ? JSON.stringify({ text: validation.text }) : validation.message;
    return Promise.resolve(result);
  },
};

type EchoTextValidation =
  | { readonly valid: true; readonly text: string }
  | { readonly valid: false; readonly message: string };

function validateEchoText(input: unknown): EchoTextValidation {
  if (!isRecord(input) || Object.keys(input).length !== 1 || typeof input.text !== 'string') {
    return { valid: false, message: 'echo_text requires exactly one string field named text.' };
  }
  const text = input.text.trim();
  if (!text) {
    return { valid: false, message: 'echo_text text must not be empty.' };
  }
  if (text.length > MAXIMUM_TEXT_LENGTH) {
    return {
      valid: false,
      message: `echo_text text must not exceed ${String(MAXIMUM_TEXT_LENGTH)} characters.`,
    };
  }
  return { valid: true, text };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
