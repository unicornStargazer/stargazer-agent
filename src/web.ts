#!/usr/bin/env node

/**
 * 提供 Chat Agent 的同源 Web 入口。
 *
 * 负责静态页面、HTTP 输入校验和错误映射；对话状态仍由 ChatAgent 管理，密钥只从环境变量读取。
 */

import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { ChatMessage } from './chat/index.js';
import { ChatAgent } from './chat/index.js';
import { OpenAICompatibleChatModel } from './providers/index.js';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3000;
const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_MESSAGE_LENGTH = 16_000;
const MAX_SESSION_ID_LENGTH = 128;
const MAX_REQUEST_ID_LENGTH = 128;
const CONTENT_TYPES: Readonly<Record<string, string>> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};

interface WebAgent {
  chat(sessionId: string, text: string): Promise<ChatMessage>;
  history(sessionId: string): readonly ChatMessage[];
  clearHistory(sessionId: string): void;
}

export interface WebServerOptions {
  readonly agent: WebAgent;
  readonly modelName?: string | undefined;
  readonly publicDirectory?: string | undefined;
}

interface ChatRequestBody {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
}

interface CompletedChatRequest {
  readonly requestMessage: string;
  readonly responseMessage: ChatMessage;
}

interface InFlightChatRequest {
  readonly requestMessage: string;
  readonly response: Promise<ChatMessage>;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

/** 创建可被测试和上层进程托管的 Web 服务。 */
export function createWebServer(options: WebServerOptions): Server {
  const publicDirectory = resolve(options.publicDirectory ?? resolve(process.cwd(), 'web', 'dist'));
  const completedRequests = new Map<string, CompletedChatRequest>();
  const inFlightRequests = new Map<string, InFlightChatRequest>();
  const sessionQueues = new Map<string, Promise<void>>();

  return createServer((request, response) => {
    void handleRequest({
      request,
      response,
      options,
      publicDirectory,
      completedRequests,
      inFlightRequests,
      sessionQueues,
    });
  });
}

interface RequestContext {
  readonly request: IncomingMessage;
  readonly response: ServerResponse;
  readonly options: WebServerOptions;
  readonly publicDirectory: string;
  readonly completedRequests: Map<string, CompletedChatRequest>;
  readonly inFlightRequests: Map<string, InFlightChatRequest>;
  readonly sessionQueues: Map<string, Promise<void>>;
}

async function handleRequest(context: RequestContext): Promise<void> {
  const { request, response } = context;
  try {
    const requestUrl = new URL(request.url ?? '/', 'http://localhost');
    if (requestUrl.pathname.startsWith('/api/')) {
      await handleApiRequest(context, requestUrl);
      return;
    }
    await serveStaticAsset(
      response,
      request.method ?? 'GET',
      requestUrl.pathname,
      context.publicDirectory,
    );
  } catch (error: unknown) {
    if (response.headersSent) {
      response.end();
      return;
    }
    if (error instanceof HttpError) {
      sendError(response, error.status, error.code, error.message);
      return;
    }
    sendError(response, 500, 'INTERNAL_ERROR', '服务暂时不可用，请稍后重试。');
  }
}

async function handleApiRequest(context: RequestContext, requestUrl: URL): Promise<void> {
  const { request, response, options } = context;
  if (requestUrl.pathname === '/api/status') {
    requireMethod(request, 'GET');
    sendJson(response, 200, {
      ready: true,
      model: options.modelName ?? 'OpenAI compatible model',
      conversationStorage: 'memory',
    });
    return;
  }

  if (requestUrl.pathname === '/api/history') {
    const sessionId = requireIdentifier(
      requestUrl.searchParams.get('sessionId'),
      'sessionId',
      MAX_SESSION_ID_LENGTH,
    );
    if (request.method === 'GET') {
      sendJson(response, 200, { messages: options.agent.history(sessionId) });
      return;
    }
    if (request.method === 'DELETE') {
      deleteConversation(context, sessionId);
      sendJson(response, 200, { deleted: true });
      return;
    }
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该接口不支持当前请求方法。');
  }

  if (requestUrl.pathname === '/api/chat') {
    requireMethod(request, 'POST');
    const body = validateChatRequest(await readJsonBody(request));
    const message = await completeChatRequest(context, body);
    sendJson(response, 200, { message });
    return;
  }

  throw new HttpError(404, 'NOT_FOUND', '请求的接口不存在。');
}

function deleteConversation(context: RequestContext, sessionId: string): void {
  const requestKeyPrefix = `${sessionId}\u0000`;
  const hasInFlightRequest = [...context.inFlightRequests.keys()].some((requestKey) =>
    requestKey.startsWith(requestKeyPrefix),
  );
  if (hasInFlightRequest) {
    throw new HttpError(409, 'SESSION_BUSY', '会话正在生成回复，暂时无法删除。');
  }

  context.options.agent.clearHistory(sessionId);
  for (const requestKey of context.completedRequests.keys()) {
    if (requestKey.startsWith(requestKeyPrefix)) {
      context.completedRequests.delete(requestKey);
    }
  }
}

/**
 * 处理聊天请求的完整函数
 * @param context 请求上下文，包含会话和请求相关信息
 * @param body 聊天请求体，包含会话ID、请求ID和消息内容
 * @returns 返回聊天消息的Promise
 */
async function completeChatRequest(
  context: RequestContext,  // 请求上下文对象，包含已完成和进行中的请求信息
  body: ChatRequestBody,   // 聊天请求体，包含会话ID、请求ID和消息内容
): Promise<ChatMessage> {   // 返回聊天消息的Promise
  // 构建请求键，由会话ID和请求ID组成，使用\u0000作为分隔符
  const requestKey = `${body.sessionId}\u0000${body.requestId}`;
  // 检查是否已有已完成的请求
  const completedRequest = context.completedRequests.get(requestKey);
  if (completedRequest !== undefined) {
    // 如果存在已完成请求，验证请求消息是否匹配
    requireMatchingRequestMessage(completedRequest.requestMessage, body.message);
    // 返回已完成的响应消息
    return completedRequest.responseMessage;
  }

  // 检查是否已有进行中的请求
  const existingRequest = context.inFlightRequests.get(requestKey);
  if (existingRequest !== undefined) {
    // 如果存在进行中请求，验证请求消息是否匹配
    requireMatchingRequestMessage(existingRequest.requestMessage, body.message);
    // 返回进行中请求的响应
    return existingRequest.response;
  }

  // 处理队列中的聊天请求，并捕获可能的错误
  const pendingResponse = runQueuedChat(context, body.sessionId, body.message).catch(() => {
    // 如果模型不可用，抛出502错误
    throw new HttpError(502, 'MODEL_UNAVAILABLE', '模型暂时不可用，请稍后重试。');
  });
  // 将进行中的请求添加到上下文中
  context.inFlightRequests.set(requestKey, {
    requestMessage: body.message,
    response: pendingResponse,
  });
  try {
    // 等待获取响应消息
    const message = await pendingResponse;
    // 记录已完成的请求
    rememberCompletedRequest(context.completedRequests, requestKey, body.message, message);
    // 返回响应消息
    return message;
  } finally {
    // 无论成功或失败，都删除进行中的请求记录
    context.inFlightRequests.delete(requestKey);
  }
}

async function runQueuedChat(
  context: RequestContext,
  sessionId: string,
  message: string,
): Promise<ChatMessage> {
  const previousRequest = context.sessionQueues.get(sessionId) ?? Promise.resolve();
  let releaseQueue: (() => void) | undefined;
  const currentRequest = new Promise<void>((resolveQueue) => {
    releaseQueue = resolveQueue;
  });
  context.sessionQueues.set(sessionId, currentRequest);

  await previousRequest;
  try {
    return await context.options.agent.chat(sessionId, message);
  } finally {
    releaseQueue?.();
    if (context.sessionQueues.get(sessionId) === currentRequest) {
      context.sessionQueues.delete(sessionId);
    }
  }
}

function requireMatchingRequestMessage(cachedMessage: string, requestMessage: string): void {
  if (cachedMessage !== requestMessage) {
    throw new HttpError(409, 'REQUEST_CONFLICT', 'requestId 已用于其他消息。');
  }
}

function rememberCompletedRequest(
  completedRequests: Map<string, CompletedChatRequest>,
  requestKey: string,
  requestMessage: string,
  message: ChatMessage,
): void {
  completedRequests.set(requestKey, { requestMessage, responseMessage: message });
  if (completedRequests.size > 500) {
    const oldestRequestKey = completedRequests.keys().next().value;
    if (oldestRequestKey !== undefined) {
      completedRequests.delete(oldestRequestKey);
    }
  }
}

async function serveStaticAsset(
  response: ServerResponse,
  method: string,
  pathname: string,
  publicDirectory: string,
): Promise<void> {
  if (method !== 'GET' && method !== 'HEAD') {
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该资源不支持当前请求方法。');
  }
  const { filePath, relativePath } = resolveStaticAsset(publicDirectory, pathname);

  let content: Buffer;
  try {
    content = await readFile(filePath);
  } catch (error: unknown) {
    if (isFileNotFoundError(error)) {
      throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
    }
    throw new HttpError(500, 'ASSET_UNAVAILABLE', '页面资源暂时不可用。');
  }

  writeSecurityHeaders(response);
  response.writeHead(200, {
    'Cache-Control': relativePath.startsWith(`assets${sep}`)
      ? 'public, max-age=31536000, immutable'
      : 'no-cache',
    'Content-Length': content.byteLength,
    'Content-Type': CONTENT_TYPES[extname(filePath).toLowerCase()] ?? 'application/octet-stream',
  });
  response.end(method === 'HEAD' ? undefined : content);
}

function resolveStaticAsset(
  publicDirectory: string,
  pathname: string,
): { readonly filePath: string; readonly relativePath: string } {
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(pathname);
  } catch {
    throw new HttpError(400, 'INVALID_PATH', '资源路径格式不正确。');
  }

  const requestedPath = decodedPath === '/' ? '/index.html' : decodedPath;
  const filePath = resolve(publicDirectory, `.${requestedPath}`);
  const relativePath = relative(publicDirectory, filePath);
  const outsidePublicDirectory =
    relativePath === '..' || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath);
  if (outsidePublicDirectory || relativePath.includes('\u0000')) {
    throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
  }
  return { filePath, relativePath };
}

function isFileNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error) || !('code' in error)) {
    return false;
  }
  const errorCode = (error as NodeJS.ErrnoException).code;
  return errorCode === 'ENOENT' || errorCode === 'EISDIR';
}

async function readJsonBody(request: IncomingMessage): Promise<unknown> {
  const contentType = request.headers['content-type'] ?? '';
  const mediaType = contentType.split(';', 1).at(0)?.trim().toLowerCase();
  if (mediaType !== 'application/json') {
    throw new HttpError(415, 'UNSUPPORTED_MEDIA_TYPE', '请求必须使用 application/json。');
  }

  const declaredLength = Number(request.headers['content-length'] ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    throw new HttpError(413, 'REQUEST_TOO_LARGE', '请求内容过大。');
  }

  const chunks: Buffer[] = [];
  let byteLength = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as Uint8Array);
    byteLength += buffer.byteLength;
    if (byteLength > MAX_REQUEST_BYTES) {
      throw new HttpError(413, 'REQUEST_TOO_LARGE', '请求内容过大。');
    }
    chunks.push(buffer);
  }

  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown;
  } catch {
    throw new HttpError(400, 'INVALID_JSON', '请求内容不是有效的 JSON。');
  }
}

function validateChatRequest(value: unknown): ChatRequestBody {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new HttpError(400, 'INVALID_REQUEST', '请求内容必须是 JSON 对象。');
  }
  const body = value as Record<string, unknown>;
  const sessionId = requireIdentifier(body.sessionId, 'sessionId', MAX_SESSION_ID_LENGTH);
  const requestId = requireIdentifier(body.requestId, 'requestId', MAX_REQUEST_ID_LENGTH);
  const message = requireText(body.message, 'message', MAX_MESSAGE_LENGTH);
  return { sessionId, requestId, message };
}

function requireIdentifier(value: unknown, fieldName: string, maximumLength: number): string {
  const identifier = requireText(value, fieldName, maximumLength);
  if (!/^[a-zA-Z0-9_-]+$/.test(identifier)) {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 格式不正确。`);
  }
  return identifier;
}

function requireText(value: unknown, fieldName: string, maximumLength: number): string {
  if (typeof value !== 'string') {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 必须是字符串。`);
  }
  const normalizedValue = value.trim();
  if (!normalizedValue) {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 不能为空。`);
  }
  if (normalizedValue.length > maximumLength) {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 超出长度限制。`);
  }
  return normalizedValue;
}

function requireMethod(request: IncomingMessage, expectedMethod: string): void {
  if (request.method !== expectedMethod) {
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该接口不支持当前请求方法。');
  }
}

/**
 * 发送JSON响应的函数
 * @param response - ServerResponse对象，用于构建HTTP响应
 * @param status - HTTP状态码
 * @param body - 要发送的响应体数据，可以是任何可序列化的值
 */
function sendJson(response: ServerResponse, status: number, body: unknown): void {
  // 将响应体数据转换为JSON字符串，然后转换为Buffer
  const content = Buffer.from(JSON.stringify(body), 'utf8');
  // 写入安全相关的HTTP头
  writeSecurityHeaders(response);
  // 设置响应状态码和头部信息
  response.writeHead(status, {
    'Cache-Control': 'no-store',           // 禁止缓存响应
    'Content-Length': content.byteLength,   // 设置响应内容的字节长度
    'Content-Type': 'application/json; charset=utf-8',  // 指定响应内容类型为JSON，字符集为UTF-8
  });
  // 发送响应内容并结束响应
  response.end(content);
}

function sendError(response: ServerResponse, status: number, code: string, message: string): void {
  sendJson(response, status, { error: { code, message } });
}

function writeSecurityHeaders(response: ServerResponse): void {
  response.setHeader(
    'Content-Security-Policy',
    "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'",
  );
  response.setHeader('Referrer-Policy', 'no-referrer');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('X-Frame-Options', 'DENY');
}

/** 从环境变量创建 Agent 并启动 Web 服务。 */
export async function main(): Promise<number> {
  try {
    const modelName = requireEnvironment('OPENAI_MODEL');
    const agent = new ChatAgent({
      model: new OpenAICompatibleChatModel({
        apiKey: requireEnvironment('OPENAI_API_KEY'),
        model: modelName,
        baseUrl: process.env.OPENAI_BASE_URL,
      }),
      systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT,
    });
    const server = createWebServer({ agent, modelName });
    const host = process.env.HOST?.trim() || DEFAULT_HOST;
    const port = parsePort(process.env.PORT);
    await listen(server, port, host);
    process.stdout.write(`Stargazer Web 已启动: http://${host}:${String(port)}\n`);
    return 0;
  } catch (error: unknown) {
    process.stderr.write(`错误: ${errorMessage(error)}\n`);
    return 2;
  }
}

function requireEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} 不能为空`);
  }
  return value;
}

function parsePort(value: string | undefined): number {
  if (value === undefined || !value.trim()) {
    return DEFAULT_PORT;
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('PORT 必须是 1 到 65535 之间的整数');
  }
  return port;
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen);
    server.listen(port, host, () => {
      server.off('error', rejectListen);
      resolveListen();
    });
  });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const entryPath = process.argv[1];
if (entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
