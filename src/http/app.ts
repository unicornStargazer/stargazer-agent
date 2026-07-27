/**
 * Fastify HTTP adapter for the Agent runtime.
 * It translates HTTP and SSE requests to application commands without accessing SQLite or models directly.
 */

import fastify from 'fastify';
import fastifyStatic from '@fastify/static';
import type { FastifyInstance, FastifyReply } from 'fastify';
import { resolve } from 'node:path';

import {
  ConversationService,
  RequestConflictError,
  SessionBusyError,
} from '../application/conversation-service.js';
import type { ConversationAgent } from '../application/conversation-service.js';
import { ConversationStoreError } from '../chat/index.js';
import type { ChatMessage, ModelStreamEvent } from '../chat/index.js';
import { ConversationProfileConflictError, UnknownAgentProfileError } from '../profiles/index.js';
import type { ProfileAgent } from '../profiles/index.js';
import { HttpError } from './http-error.js';
import { requireIdentifier, validateChatRequest } from './request-validation.js';

const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_MESSAGE_LENGTH = 16_000;
const MAX_SESSION_ID_LENGTH = 128;

type ConversationStorageKind = 'memory' | 'sqlite';

export interface WebAgent {
  chat(sessionId: string, text: string): Promise<ChatMessage>;
  history(sessionId: string): Promise<readonly ChatMessage[]>;
  clearHistory(sessionId: string): Promise<void>;
}

export interface AgentHttpAppOptions {
  readonly agent: WebAgent;
  readonly profileAgent?: ProfileAgent | undefined;
  readonly modelName?: string | undefined;
  readonly publicDirectory?: string | undefined;
  readonly conversationStorage?: ConversationStorageKind | undefined;
}

/**
 * 创建一个HTTP应用程序实例
 * @param options - AgentHttpAppOptions类型的配置选项，包含应用程序所需的配置参数
 * @returns 返回一个FastifyInstance实例，表示配置好的HTTP应用程序
 */
export function createHttpApp(options: AgentHttpAppOptions): FastifyInstance {
  // 创建Fastify实例，设置请求体大小限制和禁用日志记录
  const app = fastify({ bodyLimit: MAX_REQUEST_BYTES, logger: false });
  // 创建对话服务实例，使用提供的配置选项创建对话代理
  const conversationService = new ConversationService(createConversationAgent(options));

  // 注册安全头中间件，增强应用安全性
  registerSecurityHeaders(app);
  // 注册错误处理中间件，统一处理应用错误
  registerErrorHandler(app);
  // 注册API路由，配置应用的所有API端点
  registerApiRoutes(app, options, conversationService);
  // 注册静态资源路由，提供静态文件服务
  registerStaticRoutes(app, options.publicDirectory);
  // 返回配置完成的Fastify应用实例
  return app;
}

/**
 * 创建一个对话代理对象
 * @param options 配置选项，包含代理应用所需的配置信息
 * @returns 返回一个配置好的对话代理对象
 */
function createConversationAgent(options: AgentHttpAppOptions): ConversationAgent {
  return {
    /**
     * 处理聊天消息的方法
     * @param sessionId 会话ID
     * @param profileId 用户档案ID
     * @param message 用户输入的消息
     * @returns 返回聊天响应结果，如果profileAgent不存在则使用agent处理
     */
    chat: (sessionId, profileId, message) =>
      options.profileAgent?.chat(sessionId, profileId, message) ??
      options.agent.chat(sessionId, message),
    /**
     * 异步生成聊天流响应的方法
     * @param sessionId 会话ID
     * @param profileId 用户档案ID
     * @param message 用户输入的消息
     * @returns 返回一个异步生成器，产生聊天内容的流式响应
     */
    async *chatStream(sessionId, profileId, message) {
      // 如果存在profileAgent，则使用profileAgent处理聊天流
      if (options.profileAgent !== undefined) {
        yield* options.profileAgent.chatStream(sessionId, profileId, message);
        return;
      }
      // 否则使用agent处理聊天流，并返回内容
      yield { type: 'content', content: (await options.agent.chat(sessionId, message)).content };
    },
    /**
     * 清除聊天历史记录的方法
     * @param sessionId 会话ID
     */
    clearHistory: (sessionId) => options.agent.clearHistory(sessionId),
  };
}

/**
 * 注册安全HTTP头部的函数
 * @param app - Fastify应用实例
 */
function registerSecurityHeaders(app: FastifyInstance): void {
  // 添加发送响应前的钩子，用于设置安全HTTP头
  app.addHook('onSend', async (_request, reply, payload) => {
    // 设置内容安全策略(CSP)，限制资源加载来源
    reply.header(
      'Content-Security-Policy',
      "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
    );
    // 设置引用策略，防止发送完整的引用信息
    reply.header('Referrer-Policy', 'no-referrer');
    // 防止MIME类型嗅探，减少XSS攻击风险
    reply.header('X-Content-Type-Options', 'nosniff');
    // 防止点击劫持，拒绝被嵌入到iframe中
    reply.header('X-Frame-Options', 'DENY');
    // 返回原始载荷，不进行修改
    return payload;
  });
}

function registerErrorHandler(app: FastifyInstance): void {
  app.setErrorHandler((error, _request, reply) => {
    const mappedError = mapHttpError(error);
    void reply
      .code(mappedError.status)
      .type('application/json; charset=utf-8')
      .send({ error: { code: mappedError.code, message: mappedError.message } });
  });
}

/**
 * 注册API路由函数
 * @param app - Fastify应用实例
 * @param options - Agent HTTP应用配置选项
 * @param conversationService - 对话服务实例
 */
function registerApiRoutes(
  app: FastifyInstance,
  options: AgentHttpAppOptions,
  conversationService: ConversationService,
): void {
  // 获取API状态接口
  app.get('/api/status', () => ({
    ready: true,
    model: options.modelName ?? 'OpenAI compatible model', // 模型名称，默认为OpenAI兼容模型
    conversationStorage: options.conversationStorage ?? 'memory', // 对话存储方式，默认为内存存储
    defaultProfile: options.profileAgent?.defaultProfile(), // 默认配置档案
  }));

  // 获取所有配置档案接口
  app.get('/api/profiles', () => ({
    profiles: options.profileAgent?.profiles() ?? [], // 返回所有配置档案，如果没有则为空数组
  }));

  // 获取对话历史接口
  app.get<{ Querystring: { readonly sessionId?: string } }>('/api/history', async (request) => {
    const sessionId = requireIdentifier(
      request.query.sessionId,
      'sessionId',
      MAX_SESSION_ID_LENGTH, // 会话ID最大长度限制
    );
    return { messages: await options.agent.history(sessionId) }; // 返回指定会话的消息历史
  });

  // 删除对话历史接口
  app.delete<{ Querystring: { readonly sessionId?: string } }>('/api/history', async (request) => {
    const sessionId = requireIdentifier(
      request.query.sessionId,
      'sessionId',
      MAX_SESSION_ID_LENGTH, // 会话ID最大长度限制
    );
    await conversationService.clear(sessionId); // 清除指定会话的对话历史
    return { deleted: true }; // 返回删除成功标志
  });

  // 发送聊天消息接口
  app.post('/api/chat', async (request) => {
    const command = validateChatRequest(request.body, MAX_MESSAGE_LENGTH, MAX_SESSION_ID_LENGTH); // 验证聊天请求
    return { message: await conversationService.chat(command) }; // 返回聊天响应
  });

  // 流式聊天接口
  app.post('/api/chat/stream', async (request, reply) => {
    if (options.profileAgent === undefined) {
      throw new HttpError(501, 'STREAMING_UNAVAILABLE', '当前服务未启用流式聊天'); // 如果未启用流式聊天，抛出错误
    }
    const command = validateChatRequest(request.body, MAX_MESSAGE_LENGTH, MAX_SESSION_ID_LENGTH); // 验证聊天请求
    await sendStream(reply, conversationService, command); // 发送流式响应
  });
}

function registerStaticRoutes(app: FastifyInstance, configuredDirectory: string | undefined): void {
  const publicDirectory = resolve(configuredDirectory ?? resolve(process.cwd(), 'web', 'dist'));
  void app.register(fastifyStatic, { root: publicDirectory, serve: false });

  app.get('/', async (_request, reply) => sendStaticFile(reply, 'index.html'));
  app.get<{ Params: { readonly '*': string } }>('/*', async (request, reply) => {
    const path = request.params['*'];
    if (!path || path.startsWith('api/') || isUnsafeStaticPath(path, request.raw.url)) {
      throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
    }
    return sendStaticFile(reply, path);
  });
}

function isUnsafeStaticPath(path: string, rawUrl: string | undefined): boolean {
  const rawPath = rawUrl?.split('?', 1)[0] ?? path;
  try {
    return decodeURIComponent(rawPath).replaceAll('\\', '/').split('/').includes('..');
  } catch {
    return true;
  }
}

function sendStaticFile(reply: FastifyReply, path: string): FastifyReply {
  const immutable = path.startsWith('assets/');
  reply.header('Cache-Control', immutable ? 'public, max-age=31536000, immutable' : 'no-cache');
  return reply.sendFile(path);
}

/**
 * 发送流式响应的异步函数
 * @param reply - FastifyReply对象，用于处理HTTP响应
 * @param conversationService - 对话服务实例，用于处理流式数据
 * @param command - 传递给conversationService.stream的参数
 * @returns Promise<void>
 */
async function sendStream(
  reply: FastifyReply, // Fastify响应对象，用于处理HTTP响应
  conversationService: ConversationService, // 对话服务，提供流式数据功能
  command: Parameters<ConversationService['stream']>[0], // 传递给stream方法的参数
): Promise<void> {
  reply.hijack(); // 劫持原始响应对象，以便直接操作底层流
  reply.raw.writeHead(200, {
    // 设置响应头，使用SSE（Server-Sent Events）格式
    'Cache-Control': 'no-store', // 禁用缓存
    Connection: 'keep-alive', // 保持连接
    'Content-Type': 'text/event-stream; charset=utf-8', // SSE内容类型
    // 内容安全策略
    'Content-Security-Policy':
      "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
    'Referrer-Policy': 'no-referrer', // 不发送引用页面的URL
    'X-Content-Type-Options': 'nosniff', // 防止MIME类型嗅探
    'X-Frame-Options': 'DENY', // 防止点击劫持
  });
  try {
    // 调用对话服务的stream方法，处理流式数据
    await conversationService.stream(command, (event) => {
      writeStreamEvent(reply, event);
    });
    reply.raw.end('event: done\ndata: {}\n\n'); // 流结束信号
  } catch (error) {
    // 发送错误信息
    reply.raw.end(`event: error\ndata: ${JSON.stringify(mapStreamError(error))}\n\n`);
  }
}

function writeStreamEvent(reply: FastifyReply, event: ModelStreamEvent): void {
  const eventName = event.type === 'content' ? 'chunk' : event.type;
  const payload = event.type === 'usage' ? { usage: event.usage } : { content: event.content };
  reply.raw.write(`event: ${eventName}\ndata: ${JSON.stringify(payload)}\n\n`);
}

function mapHttpError(error: unknown): HttpError {
  if (error instanceof HttpError) {
    return error;
  }
  if (error instanceof RequestConflictError) {
    return new HttpError(409, 'REQUEST_CONFLICT', error.message);
  }
  if (error instanceof SessionBusyError) {
    return new HttpError(409, 'SESSION_BUSY', error.message);
  }
  if (error instanceof UnknownAgentProfileError) {
    return new HttpError(400, 'UNKNOWN_PROFILE', '请求的 Agent Profile 不存在');
  }
  if (error instanceof ConversationProfileConflictError) {
    return new HttpError(409, 'PROFILE_CONFLICT', '会话已绑定其他 Agent Profile');
  }
  if (error instanceof ConversationStoreError) {
    return new HttpError(
      503,
      'CONVERSATION_STORAGE_UNAVAILABLE',
      '会话存储暂时不可用，请稍后重试。',
    );
  }
  if (isFastifyPayloadError(error)) {
    return new HttpError(413, 'REQUEST_TOO_LARGE', '请求内容过大。');
  }
  if (getFastifyErrorCode(error) === 'FST_ERR_CTP_INVALID_MEDIA_TYPE') {
    return new HttpError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Content-Type 必须为 application/json。');
  }
  if (getFastifyErrorCode(error) === 'FST_ERR_CTP_INVALID_JSON') {
    return new HttpError(400, 'INVALID_REQUEST', '请求内容必须是 JSON 对象。');
  }
  return new HttpError(502, 'MODEL_UNAVAILABLE', '模型暂时不可用，请稍后重试。');
}

function mapStreamError(error: unknown): { readonly code: string; readonly message: string } {
  const mappedError = mapHttpError(error);
  return { code: mappedError.code, message: mappedError.message };
}

function isFastifyPayloadError(error: unknown): boolean {
  return getFastifyErrorCode(error) === 'FST_ERR_CTP_BODY_TOO_LARGE';
}

function getFastifyErrorCode(error: unknown): string | undefined {
  if (!(error instanceof Error) || !('code' in error)) {
    return undefined;
  }
  const { code } = error as { readonly code?: unknown };
  return typeof code === 'string' ? code : undefined;
}
