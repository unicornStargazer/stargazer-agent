/**
 * 定义对话核心所需的模型端口。
 *
 * 负责隔离 ChatAgent 与模型供应商；不定义流式输出、工具调用或重试策略。仅依赖消息类型。
 */

import type { ChatMessage } from './models.js';

export interface ChatModel {
  /**
   * 根据已组装的有序消息返回一段完整助手文本。
   *
   * 实现不得修改输入数组；网络或供应商错误应以异常传递，不能伪造空回复。
   */
  complete(messages: readonly ChatMessage[]): Promise<string>;
}
