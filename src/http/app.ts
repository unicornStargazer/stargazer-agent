/** Fastify 应用装配入口，只负责组合 HTTP 适配器，不承载业务规则。 */

import fastify from 'fastify';
import type { FastifyInstance } from 'fastify';

import { ConversationService } from '../application/conversation-service.js';
import { registerApiRoutes } from './api-routes.js';
import { createConversationAgent } from './conversation-agent-adapter.js';
import { registerErrorHandler } from './error-mapper.js';
import { registerSecurityHeaders } from './security-headers.js';
import { registerStaticRoutes } from './static-routes.js';
import type { AgentHttpAppOptions } from './types.js';

const MAX_REQUEST_BYTES = 32 * 1024;

export type { AgentHttpAppOptions, WebAgent } from './types.js';

export function createHttpApp(options: AgentHttpAppOptions): FastifyInstance {
  const app = fastify({ bodyLimit: MAX_REQUEST_BYTES, logger: false });
  const conversationService = new ConversationService(createConversationAgent(options));

  registerSecurityHeaders(app);
  registerErrorHandler(app);
  registerApiRoutes(app, options, conversationService);
  registerStaticRoutes(app, options.publicDirectory);

  return app;
}
