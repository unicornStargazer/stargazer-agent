/** 模型 Provider 的领域端口，隔离 ChatAgent 与具体 SDK 或 HTTP 协议。 */

import type { ChatMessage, ModelTokenUsage, ToolCall } from './models.js';
import type { ToolDefinition } from '../tools/tool.js';

export interface ToolCallingCompletion {
  readonly content: string;
  readonly toolCalls: readonly ToolCall[];
}

export type ModelStreamEvent =
  | { readonly type: 'content'; readonly content: string }
  | { readonly type: 'reasoning'; readonly content: string }
  | { readonly type: 'usage'; readonly usage: ModelTokenUsage };

export interface ChatModel {
  /** 返回完整文本；Provider 故障必须以异常传递，不能伪造空回答。 */
  complete(messages: readonly ChatMessage[]): Promise<string>;
  completeWithTools?(
    messages: readonly ChatMessage[],
    tools: readonly ToolDefinition[],
  ): Promise<ToolCallingCompletion>;
  /** 可选的增量事件输出；不支持时调用方可以退回 complete。 */
  stream?(messages: readonly ChatMessage[]): AsyncIterable<ModelStreamEvent>;
}
