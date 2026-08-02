/** 面向浏览器的 Controller：仅完成参数绑定、用例调用和协议输出。 */

import type { FastifyInstance } from 'fastify';

import type { ConversationService } from '../application/conversation-service.js';
import { HttpError } from './http-error.js';
import { requireIdentifier, validateChatRequest } from './request-validation.js';
import { writeConversationStream } from './streaming-response.js';
import type { AgentHttpAppOptions } from './types.js';

const MAX_MESSAGE_LENGTH = 16_000;
const MAX_SESSION_ID_LENGTH = 128;

export function registerApiRoutes(
  app: FastifyInstance,
  options: AgentHttpAppOptions,
  conversationService: ConversationService,
): void {
  app.get('/api/status', () => ({
    ready: true,
    model: options.modelName ?? 'OpenAI compatible model',
    conversationStorage: options.conversationStorage ?? 'memory',
    defaultProfile: options.profileAgent?.defaultProfile(),
  }));

  app.get('/api/profiles', () => ({ profiles: options.profileAgent?.profiles() ?? [] }));

  app.get<{ Querystring: { readonly sessionId?: string } }>('/api/history', async (request) => {
    const sessionId = sessionIdFrom(request.query.sessionId);
    return { messages: await options.agent.history(sessionId) };
  });

  app.delete<{ Querystring: { readonly sessionId?: string } }>('/api/history', async (request) => {
    await conversationService.clear(sessionIdFrom(request.query.sessionId));
    return { deleted: true };
  });

  app.post('/api/chat', async (request) => {
    const command = chatCommandFrom(request.body);
    return { message: await conversationService.chat(command) };
  });

  app.post('/api/chat/stream', async (request, reply) => {
    if (options.profileAgent === undefined) {
      throw new HttpError(501, 'STREAMING_UNAVAILABLE', '当前服务未启用流式聊天。');
    }
    await writeConversationStream(reply, conversationService, chatCommandFrom(request.body));
  });
}

function sessionIdFrom(value: unknown): string {
  return requireIdentifier(value, 'sessionId', MAX_SESSION_ID_LENGTH);
}

function chatCommandFrom(body: unknown) {
  return validateChatRequest(body, MAX_MESSAGE_LENGTH, MAX_SESSION_ID_LENGTH);
}
