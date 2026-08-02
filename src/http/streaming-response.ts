/**
 * 将应用层流事件编码为 SSE。
 *
 * 常规响应会经过 Fastify 的 onSend 钩子；SSE 在这里直接接管原始响应，
 * 因而需要显式写入与常规接口相同的安全响应头。
 */

import type { FastifyReply } from 'fastify';

import type { ConversationService } from '../application/conversation-service.js';
import type { ModelStreamEvent } from '../chat/index.js';
import { mapHttpError } from './error-mapper.js';
import { SECURITY_HEADERS } from './security-headers.js';

/**
 * 将一次流式对话写入已经接管的 HTTP 响应。
 *
 * 异常发生时 HTTP 200 响应头已经发送，故错误必须作为 SSE `error` 事件传递，
 * 由前端统一展示，而不能再尝试改写 HTTP 状态码。
 */
export async function writeConversationStream(
  reply: FastifyReply,
  conversationService: ConversationService,
  command: Parameters<ConversationService['stream']>[0],
): Promise<void> {
  reply.hijack();
  reply.raw.writeHead(200, {
    ...SECURITY_HEADERS,
    'Cache-Control': 'no-store',
    Connection: 'keep-alive',
    'Content-Type': 'text/event-stream; charset=utf-8',
  });

  try {
    await conversationService.stream(command, (event) => writeEvent(reply, event));
    reply.raw.end('event: done\ndata: {}\n\n');
  } catch (error) {
    const mappedError = mapHttpError(error);
    reply.raw.end(
      `event: error\ndata: ${JSON.stringify({ code: mappedError.code, message: mappedError.message })}\n\n`,
    );
  }
}

/** 将领域事件映射为前端约定的 SSE 事件名与数据结构。 */
function writeEvent(reply: FastifyReply, event: ModelStreamEvent): void {
  const eventName = event.type === 'content' ? 'chunk' : event.type;
  const payload = event.type === 'usage' ? { usage: event.usage } : { content: event.content };
  reply.raw.write(`event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`);
}
