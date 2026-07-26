import { describe, expect, it } from 'vitest';

import { ChatAgent } from '../../src/chat/agent.js';
import type { ChatMessage, ChatModel, ToolCallingCompletion } from '../../src/chat/index.js';
import { ToolRegistry } from '../../src/tools/index.js';
import type { ToolDefinition } from '../../src/tools/index.js';

describe('ToolRegistry', () => {
  it('only executes explicitly registered tools and converts invalid arguments to a model-visible result', async () => {
    const registry = new ToolRegistry([
      {
        name: 'lookup_weather',
        description: 'Looks up a weather forecast.',
        parameters: { type: 'object' },
        execute: (input) => Promise.resolve(`Forecast for ${(input as { city: string }).city}`),
      },
    ]);

    await expect(registry.execute('unknown_tool', '{}', { sessionId: 'session-1' })).resolves.toBe(
      "Tool 'unknown_tool' is not available.",
    );
    await expect(
      registry.execute('lookup_weather', '{not json}', { sessionId: 'session-1' }),
    ).resolves.toBe('Tool arguments must be valid JSON.');
  });
});

describe('ChatAgent tool orchestration', () => {
  it('runs registered tools, returns the final model answer, and persists only the visible turn', async () => {
    const model = new ToolCallingFakeModel();
    const agent = new ChatAgent({
      model,
      tools: new ToolRegistry([
        {
          name: 'lookup_weather',
          description: 'Looks up a weather forecast.',
          parameters: { type: 'object', properties: { city: { type: 'string' } } },
          execute: (input, context) => {
            expect(context.sessionId).toBe('session-1');
            expect(input).toEqual({ city: 'Shanghai' });
            return Promise.resolve('Shanghai: sunny, 28C');
          },
        },
      ]),
    });

    await expect(agent.chat('session-1', 'How is the weather?')).resolves.toEqual({
      role: 'assistant',
      content: 'Shanghai is sunny and 28C.',
    });
    await expect(agent.history('session-1')).resolves.toEqual([
      { role: 'user', content: 'How is the weather?' },
      { role: 'assistant', content: 'Shanghai is sunny and 28C.' },
    ]);
    expect(model.requests).toHaveLength(2);
    expect(model.requests[1]).toContainEqual({
      role: 'tool',
      name: 'lookup_weather',
      toolCallId: 'call-1',
      content: 'Shanghai: sunny, 28C',
    });
  });

  it('stops a repeated tool request at the configured round limit', async () => {
    const model = new ToolCallingFakeModel(true);
    const agent = new ChatAgent({
      model,
      maximumToolRounds: 1,
      tools: new ToolRegistry([
        {
          name: 'lookup_weather',
          description: 'Looks up a weather forecast.',
          parameters: { type: 'object' },
          execute: () => Promise.resolve('sunny'),
        },
      ]),
    });

    await expect(agent.chat('session-1', 'Weather?')).rejects.toThrow(
      'Tool call limit (1) exceeded.',
    );
  });
});

class ToolCallingFakeModel implements ChatModel {
  readonly requests: ChatMessage[][] = [];

  constructor(private readonly alwaysRequestTool = false) {}

  complete(): Promise<string> {
    return Promise.reject(new Error('Tool-enabled agent should use completeWithTools.'));
  }

  completeWithTools(
    messages: readonly ChatMessage[],
    tools: readonly ToolDefinition[],
  ): Promise<ToolCallingCompletion> {
    this.requests.push([...messages]);
    expect(tools.map((tool) => tool.name)).toEqual(['lookup_weather']);
    if (this.alwaysRequestTool || messages.at(-1)?.role !== 'tool') {
      return Promise.resolve({
        content: '',
        toolCalls: [
          {
            id: `call-${String(this.requests.length)}`,
            name: 'lookup_weather',
            arguments: '{"city":"Shanghai"}',
          },
        ],
      });
    }
    return Promise.resolve({ content: 'Shanghai is sunny and 28C.', toolCalls: [] });
  }
}
