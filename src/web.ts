#!/usr/bin/env node

/**
 * 提供同源 Web 页面和 HTTP API。
 *
 * 本模块处理协议校验、请求协调和错误映射；不保存业务状态，也不直接执行 SQLite 查询。
 */

import { mkdir, readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { dirname, extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ChatAgent, ConversationStoreError } from './chat/index.js';
import type { ChatMessage } from './chat/index.js';
import { SqliteConversationStore } from './memory/index.js';
import { OpenAICompatibleChatModel } from './providers/index.js';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3000;
const DEFAULT_DATABASE_FILE = 'stargazer-agent.sqlite';
const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_MESSAGE_LENGTH = 16_000;
const MAX_SESSION_ID_LENGTH = 128;
const MAX_REQUEST_ID_LENGTH = 128;
const MAX_COMPLETED_REQUESTS = 500;
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

type ConversationStorageKind = 'memory' | 'sqlite';

interface WebAgent {
  chat(sessionId: string, text: string): Promise<ChatMessage>;
  history(sessionId: string): Promise<readonly ChatMessage[]>;
  clearHistory(sessionId: string): Promise<void>;
}

export interface WebServerOptions {
  readonly agent: WebAgent;
  readonly modelName?: string | undefined;
  readonly publicDirectory?: string | undefined;
  readonly conversationStorage?: ConversationStorageKind | undefined;
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

interface RequestContext {
  readonly request: IncomingMessage;
  readonly response: ServerResponse;
  readonly options: WebServerOptions;
  readonly publicDirectory: string;
  readonly completedRequests: Map<string, CompletedChatRequest>;
  readonly inFlightRequests: Map<string, InFlightChatRequest>;
  readonly sessionQueues: Map<string, Promise<void>>;
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

/** 创建可由测试或上层进程托管的 Web 服务。 */
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
    if (error instanceof ConversationStoreError) {
      sendError(
        response,
        503,
        'CONVERSATION_STORAGE_UNAVAILABLE',
        '会话存储暂时不可用，请稍后重试。',
      );
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
      conversationStorage: options.conversationStorage ?? 'memory',
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
      sendJson(response, 200, { messages: await options.agent.history(sessionId) });
      return;
    }
    if (request.method === 'DELETE') {
      await deleteConversation(context, sessionId);
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

async function deleteConversation(context: RequestContext, sessionId: string): Promise<void> {
  const requestKeyPrefix = `${sessionId}\u0000`;
  const hasInFlightRequest = [...context.inFlightRequests.keys()].some((requestKey) =>
    requestKey.startsWith(requestKeyPrefix),
  );
  if (hasInFlightRequest) {
    throw new HttpError(409, 'SESSION_BUSY', '会话正在生成回复，暂时无法删除。');
  }

  await context.options.agent.clearHistory(sessionId);
  for (const requestKey of context.completedRequests.keys()) {
    if (requestKey.startsWith(requestKeyPrefix)) {
      context.completedRequests.delete(requestKey);
    }
  }
}

/**
 * 对同一 requestId 复用进行去重，并将不同 requestId 的同会话请求交给串行队列。
 * 失败请求不会写入已完成缓存，因此调用方可以使用同一 requestId 重试。
 */
async function completeChatRequest(
  context: RequestContext,
  body: ChatRequestBody,
): Promise<ChatMessage> {
  const requestKey = `${body.sessionId}\u0000${body.requestId}`;
  const completedRequest = context.completedRequests.get(requestKey);
  if (completedRequest !== undefined) {
    requireMatchingRequestMessage(completedRequest.requestMessage, body.message);
    return completedRequest.responseMessage;
  }

  const existingRequest = context.inFlightRequests.get(requestKey);
  if (existingRequest !== undefined) {
    requireMatchingRequestMessage(existingRequest.requestMessage, body.message);
    return existingRequest.response;
  }

  const pendingResponse = runQueuedChat(context, body.sessionId, body.message).catch(
    mapChatRequestError,
  );
  context.inFlightRequests.set(requestKey, {
    requestMessage: body.message,
    response: pendingResponse,
  });
  try {
    const message = await pendingResponse;
    rememberCompletedRequest(context.completedRequests, requestKey, body.message, message);
    return message;
  } finally {
    context.inFlightRequests.delete(requestKey);
  }
}

function mapChatRequestError(error: unknown): never {
  if (error instanceof ConversationStoreError) {
    throw new HttpError(
      503,
      'CONVERSATION_STORAGE_UNAVAILABLE',
      '会话存储暂时不可用，请稍后重试。',
    );
  }
  throw new HttpError(502, 'MODEL_UNAVAILABLE', '模型暂时不可用，请稍后重试。');
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
  if (completedRequests.size > MAX_COMPLETED_REQUESTS) {
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

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  const content = Buffer.from(JSON.stringify(body), 'utf8');
  writeSecurityHeaders(response);
  response.writeHead(status, {
    'Cache-Control': 'no-store',
    'Content-Length': content.byteLength,
    'Content-Type': 'application/json; charset=utf-8',
  });
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


/**
 * 主函数，启动 Stargazer Web 服务
 * @returns {Promise<number>} 返回状态码，0 表示成功，2 表示失败
 */
export async function main(): Promise<number> {
  try {
    // 从环境变量中获取模型名称
    const modelName = requireEnvironment('OPENAI_MODEL');
    // 解析数据库路径
    const databasePath = resolveDatabasePath();
    // 递归创建数据库目录（如果不存在）
    await mkdir(dirname(databasePath), { recursive: true });
    // 打开 SQLite 对话存储
    const conversationStore = await SqliteConversationStore.open({ databasePath });
    // 创建聊天代理，配置模型、对话存储和系统提示
    const agent = new ChatAgent({
      model: new OpenAICompatibleChatModel({
        apiKey: requireEnvironment('OPENAI_API_KEY'), // 从环境变量获取 API 密钥
        model: modelName, // 使用指定的模型
        baseUrl: process.env.OPENAI_BASE_URL, // 可选的基础 URL
      }),
      conversationStore, // 使用 SQLite 存储对话
      systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT, // 系统提示词
    });
    // 创建 Web 服务器，配置代理、模型名称和存储方式
    const server = createWebServer({ agent, modelName, conversationStorage: 'sqlite' });
    // 监听服务器关闭事件，确保正确关闭对话存储
    server.once('close', () => {
      void conversationStore.close();
    });
    // 获取主机地址，默认为 DEFAULT_HOST
    const host = process.env.HOST?.trim() || DEFAULT_HOST;
    // 解析端口号
    const port = parsePort(process.env.PORT);
    // 启动服务器监听指定主机和端口
    await listen(server, port, host);
    // 输出启动信息到标准输出
    process.stdout.write(`Stargazer Web 已启动: http://${host}:${String(port)}\n`);
    return 0; // 成功返回 0
  } catch (error: unknown) {
    // 输出错误信息到标准错误输出
    process.stderr.write(`错误: ${errorMessage(error)}\n`);
    return 2; // 失败返回 2
  }
}

/**
 * 解析数据库路径的函数
 * 根据环境变量配置返回数据库文件的完整路径
 * 如果没有配置数据库路径，则使用默认路径
 * @returns 返回数据库文件的完整路径字符串
 */
function resolveDatabasePath(): string {
  // 获取并处理环境变量中配置的数据库路径
  const configuredDatabasePath = process.env.STARGAZER_DATABASE_PATH?.trim();
  // 如果配置了数据库路径，则直接返回解析后的绝对路径
  if (configuredDatabasePath) {
    return resolve(process.cwd(), configuredDatabasePath);
  }
  // 获取并处理环境变量中配置的数据目录
  const configuredDataDirectory = process.env.STARGAZER_DATA_DIR?.trim();
  // 根据是否配置了数据目录，决定使用配置的目录还是默认的'data'目录
  const dataDirectory = configuredDataDirectory
    ? resolve(process.cwd(), configuredDataDirectory)
    : resolve(process.cwd(), 'data');
  // 返回数据目录下的默认数据库文件路径
  return resolve(dataDirectory, DEFAULT_DATABASE_FILE);
}

/**
 * 获取并验证环境变量值
 * @param name 环境变量名称
 * @returns 环境变量的值（去除首尾空格）
 * @throws 当环境变量不存在或为空时抛出错误
 */
function requireEnvironment(name: string): string {
  const value = process.env[name]?.trim(); // 获取环境变量并去除首尾空格
  if (!value) { // 检查环境变量是否存在或为空
    throw new Error(`${name} 不能为空`); // 如果为空则抛出错误
  }
  return value; // 返回环境变量的值
}

/**
 * 解析端口号字符串并验证其有效性
 * @param value - 需要解析的端口号字符串，可能为undefined
 * @returns 返回解析后的有效端口号，如果输入无效则返回默认端口号
 * @throws 当端口号不是1到65535之间的整数时抛出错误
 */
function parsePort(value: string | undefined): number {
  // 检查输入值是否为undefined或空字符串，如果是则返回默认端口号
  if (value === undefined || !value.trim()) {
    return DEFAULT_PORT;
  }
  // 将字符串转换为数字
  const port = Number(value);
  // 验证端口号是否为整数且在有效范围内(1-65535)
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('PORT 必须是 1 到 65535 之间的整数');
  }
  // 返回验证通过的端口号
  return port;
}

/**
 * 监听服务器并返回一个Promise
 * @param server - Node.js的Server实例
 * @param port - 服务器监听的端口号
 * @param host - 服务器监听的主机地址
 * @returns 返回一个Promise，在服务器成功启动时解析，在发生错误时拒绝
 */
function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolveListen, rejectListen) => {
    // 设置错误监听器，一旦发生错误则拒绝Promise
    server.once('error', rejectListen);
    // 启动服务器监听
    server.listen(port, host, () => {
      // 服务器成功启动后，移除错误监听器
      server.off('error', rejectListen);
      // 解析Promise，表示服务器已成功启动
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
