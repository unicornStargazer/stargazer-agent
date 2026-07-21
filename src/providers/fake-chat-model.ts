/**
 * 提供离线对话测试替身。
 *
 * 负责按预设顺序返回文本并记录请求；不模拟网络协议、流式事件、工具调用或供应商错误格式。
 * 仅依赖 chat 端口与 JavaScript 标准集合。
 */

import type { ChatMessage, ChatModel } from '../chat/index.js';

export class FakeChatModel implements ChatModel {
  private readonly responses: string[];
  readonly requests: ChatMessage[][] = [];

  constructor(responses: readonly string[]) {
    this.responses = [...responses];
  }

  /** 记录消息快照；预设回复耗尽时抛出异常以暴露测试遗漏。 */
  complete(messages: readonly ChatMessage[]): Promise<string> {
    this.requests.push([...messages]);
    const response = this.responses.shift();
    if (response === undefined) {
      throw new Error('FakeChatModel 没有可用的预设响应');
    }
    return Promise.resolve(response);
  }
}
