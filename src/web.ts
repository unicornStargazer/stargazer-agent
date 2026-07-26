#!/usr/bin/env node

/**
 * 提供同源 Web 页面和 HTTP API。
 *
 * 本模块处理协议校验、请求协调和错误映射；不保存业务状态，也不直接执行 SQLite 查询。
 */

import { mkdir } from 'node:fs/promises';
import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ChatAgent, ConversationStoreError } from './chat/index.js';
import type { ChatMessage } from './chat/index.js';
import {
  ConversationService,
  RequestConflictError,
  SessionBusyError,
} from './application/conversation-service.js';
import { HttpError, sendError, sendJson, writeSecurityHeaders } from './http/http-error.js';
import {
  readJsonBody,
  requireIdentifier,
  requireMethod,
  validateChatRequest,
} from './http/request-validation.js';
import type { ChatRequestBody } from './http/request-validation.js';
import { serveStaticAsset } from './http/static-assets.js';
import { SqliteConversationStore } from './memory/index.js';
import {
  ConversationProfileConflictError,
  ProfileAgent,
  UnknownAgentProfileError,
} from './profiles/index.js';
import type { AgentProfile } from './profiles/index.js';
import { OpenAICompatibleChatModel } from './providers/index.js';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3000;
const DEFAULT_DATABASE_FILE = 'stargazer-agent.sqlite';
const MAX_REQUEST_BYTES = 32 * 1024;
const MAX_MESSAGE_LENGTH = 16_000;
const MAX_SESSION_ID_LENGTH = 128;
const MAX_COMPLETED_REQUESTS = 500;

type ConversationStorageKind = 'memory' | 'sqlite';

interface WebAgent {
  chat(sessionId: string, text: string): Promise<ChatMessage>;
  history(sessionId: string): Promise<readonly ChatMessage[]>;
  clearHistory(sessionId: string): Promise<void>;
}

interface CompletedChatRequest {
  readonly requestMessage: string;
  readonly responseMessage: ChatMessage;
}
interface InFlightChatRequest {
  readonly requestMessage: string;
  readonly response: Promise<ChatMessage>;
}

export interface WebServerOptions {
  readonly agent: WebAgent;
  readonly profileAgent?: ProfileAgent | undefined;
  readonly modelName?: string | undefined;
  readonly publicDirectory?: string | undefined;
  readonly conversationStorage?: ConversationStorageKind | undefined;
}

interface RequestContext {
  readonly request: IncomingMessage;
  readonly response: ServerResponse;
  readonly options: WebServerOptions;
  readonly publicDirectory: string;
  readonly completedRequests: Map<string, CompletedChatRequest>;
  readonly inFlightRequests: Map<string, InFlightChatRequest>;
  readonly sessionQueues: Map<string, Promise<void>>;
  readonly conversationService: ConversationService;
}

/**
 * 创建一个Web服务器实例
 * @param options - Web服务器配置选项
 * @returns 返回一个创建好的服务器实例
 */
export function createWebServer(options: WebServerOptions): Server {
  // 解析公共目录路径，如果未指定则使用当前工作目录下的web/dist目录
  const publicDirectory = resolve(options.publicDirectory ?? resolve(process.cwd(), 'web', 'dist'));
  // 用于存储已完成的聊天请求
  const completedRequests = new Map<string, CompletedChatRequest>();
  const inFlightRequests = new Map<string, InFlightChatRequest>();
  const sessionQueues = new Map<string, Promise<void>>();
  const conversationService = new ConversationService(createConversationAgent(options));

  // 创建并返回一个服务器实例，配置请求处理函数
  return createServer((request, response) => {
    // 使用void操作符忽略Promise的返回值，因为我们不关心处理结果
    void handleRequest({
      request,
      response,
      options,
      publicDirectory,
      completedRequests,
      inFlightRequests,
      sessionQueues,
      conversationService,
    });
  });
}

function createConversationAgent(options: WebServerOptions) {
  return {
    chat: (sessionId: string, profileId: string | undefined, message: string) =>
      options.profileAgent?.chat(sessionId, profileId, message) ??
      options.agent.chat(sessionId, message),
    async *chatStream(sessionId: string, profileId: string | undefined, message: string) {
      if (options.profileAgent !== undefined) {
        yield* options.profileAgent.chatStream(sessionId, profileId, message);
        return;
      }
      yield (await options.agent.chat(sessionId, message)).content;
    },
    clearHistory: (sessionId: string) => options.agent.clearHistory(sessionId),
  };
}

/**
 * 处理HTTP请求的入口函数
 * @param context 请求上下文，包含请求和响应对象
 * @returns Promise<void>
 */
async function handleRequest(context: RequestContext): Promise<void> {
  const { request, response } = context; // 解构请求上下文，获取请求和响应对象
  try {
    // 创建URL对象，如果请求URL不存在则使用默认值'/'
    const requestUrl = new URL(request.url ?? '/', 'http://localhost');
    // 判断请求路径是否以'/api/'开头
    if (requestUrl.pathname.startsWith('/api/')) {
      // 如果是API请求，则调用API处理函数
      await handleApiRequest(context, requestUrl);
      return; // 处理完成后直接返回
    }
    // 如果不是API请求，则处理静态资源请求
    await serveStaticAsset(
      response,
      request.method ?? 'GET', // 如果请求方法不存在，默认使用GET方法
      requestUrl.pathname, // 请求路径
      context.publicDirectory, // 公共目录
    );
  } catch (error: unknown) {
    // 捕获处理过程中可能出现的错误
    // 如果响应头已经发送，则直接结束响应
    if (response.headersSent) {
      response.end();
      return;
    }
    // 如果是HTTP错误，则发送对应的错误响应
    if (error instanceof HttpError) {
      sendError(response, error.status, error.code, error.message);
      return;
    }
    // 如果是会话存储错误，则发送503状态码和相应的错误信息
    if (error instanceof ConversationStoreError) {
      sendError(
        response,
        503,
        'CONVERSATION_STORAGE_UNAVAILABLE',
        '会话存储暂时不可用，请稍后重试。',
      );
      return;
    }
    // 其他未知错误，则发送500状态码和通用错误信息
    sendError(response, 500, 'INTERNAL_ERROR', '服务暂时不可用，请稍后重试。');
  }
}

/**
 * 处理API请求的异步函数
 * @param context 请求上下文对象，包含请求、响应和配置选项
 * @param requestUrl 请求的URL对象
 * @returns Promise<void>
 */
async function handleApiRequest(context: RequestContext, requestUrl: URL): Promise<void> {
  // 从上下文中解构出请求、响应和选项
  const { request, response, options } = context;
  // 处理状态查询接口
  if (requestUrl.pathname === '/api/status') {
    requireMethod(request, 'GET'); // 确保请求方法为GET
    // 发送JSON响应，包含服务状态和配置信息
    sendJson(response, 200, {
      ready: true,
      model: options.modelName ?? 'OpenAI compatible model', // 默认模型名称
      conversationStorage: options.conversationStorage ?? 'memory', // 默认对话存储方式
      defaultProfile: options.profileAgent?.defaultProfile(), // 默认配置文件
    });
    return;
  }

  // 处理配置文件列表接口
  if (requestUrl.pathname === '/api/profiles') {
    requireMethod(request, 'GET'); // 确保请求方法为GET
    // 如果没有配置文件代理，返回空数组
    if (options.profileAgent === undefined) {
      sendJson(response, 200, { profiles: [] });
      return;
    }
    // 返回配置文件列表
    sendJson(response, 200, { profiles: options.profileAgent.profiles() });
    return;
  }

  // 处理对话历史接口
  if (requestUrl.pathname === '/api/history') {
    // 获取并验证会话ID
    const sessionId = requireIdentifier(
      requestUrl.searchParams.get('sessionId'),
      'sessionId',
      MAX_SESSION_ID_LENGTH,
    );
    // GET请求：获取对话历史
    if (request.method === 'GET') {
      sendJson(response, 200, { messages: await options.agent.history(sessionId) });
      return;
    }
    // DELETE请求：删除对话
    if (request.method === 'DELETE') {
      await deleteConversation(context, sessionId);
      sendJson(response, 200, { deleted: true });
      return;
    }
    // 不支持的请求方法
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该接口不支持当前请求方法。');
  }

  // 处理聊天接口
  if (requestUrl.pathname === '/api/chat') {
    requireMethod(request, 'POST'); // 确保请求方法为POST
    // 验证聊天请求体
    const body = validateChatRequest(
      await readJsonBody(request, MAX_REQUEST_BYTES),
      MAX_MESSAGE_LENGTH,
      MAX_SESSION_ID_LENGTH,
    );
    // 完成聊天请求并发送响应
    const message = await completeChatRequest(context, body);
    sendJson(response, 200, { message });
    return;
  }

  // 处理流式聊天接口
  if (requestUrl.pathname === '/api/chat/stream') {
    requireMethod(request, 'POST'); // 确保请求方法为POST
    // 验证聊天请求体
    const body = validateChatRequest(
      await readJsonBody(request, MAX_REQUEST_BYTES),
      MAX_MESSAGE_LENGTH,
      MAX_SESSION_ID_LENGTH,
    );
    // 检查是否启用流式聊天
    if (options.profileAgent === undefined) {
      throw new HttpError(501, 'STREAMING_UNAVAILABLE', '当前服务未启用流式聊天');
    }
    // 执行流式聊天响应
    await streamChatResponse(response, context.conversationService, body);
    return;
  }

  // 接口不存在
  throw new HttpError(404, 'NOT_FOUND', '请求的接口不存在。');
}

/**
 * 流式处理聊天响应
 * @param response - 服务器响应对象
 * @param profileAgent - 个人资料代理对象
 * @param body - 聊天请求体，包含会话ID、个人资料ID和消息内容
 * @returns Promise<void>
 */
async function streamChatResponse(
  response: ServerResponse, // 服务器响应对象
  conversationService: ConversationService,
  body: ChatRequestBody, // 聊天请求体
): Promise<void> {
  writeSecurityHeaders(response); // 写入安全头信息
  // 设置响应头，禁用缓存，保持连接，使用SSE格式
  response.writeHead(200, {
    'Cache-Control': 'no-store', // 不缓存响应
    Connection: 'keep-alive', // 保持连接
    'Content-Type': 'text/event-stream; charset=utf-8', // SSE格式，UTF-8编码
  });
  try {
    // 处理聊天流，遍历每个数据块
    await conversationService.stream(body, (chunk) => {
      response.write(`event: chunk\ndata: ${JSON.stringify({ content: chunk })}\n\n`);
    });
    // 发送完成事件
    response.end('event: done\ndata: {}\n\n');
  } catch (error: unknown) {
    // 捕获错误并映射为可格式化的错误对象
    const mappedError = mapStreamError(error);
    // 发送错误事件
    response.end(`event: error\ndata: ${JSON.stringify(mappedError)}\n\n`);
  }
}

function mapStreamError(error: unknown): { readonly code: string; readonly message: string } {
  if (error instanceof UnknownAgentProfileError) {
    return { code: 'UNKNOWN_PROFILE', message: '请求的 Agent Profile 不存在' };
  }
  if (error instanceof ConversationProfileConflictError) {
    return { code: 'PROFILE_CONFLICT', message: '会话已绑定其他 Agent Profile' };
  }
  if (error instanceof ConversationStoreError) {
    return {
      code: 'CONVERSATION_STORAGE_UNAVAILABLE',
      message: '会话存储暂时不可用，请稍后重试。',
    };
  }
  return { code: 'MODEL_UNAVAILABLE', message: '模型暂时不可用，请稍后重试。' };
}

async function deleteConversation(context: RequestContext, sessionId: string): Promise<void> {
  try {
    await context.conversationService.clear(sessionId);
  } catch (error) {
    if (error instanceof SessionBusyError) {
      throw new HttpError(409, 'SESSION_BUSY', error.message);
    }
    throw error;
  }
}

/**
 * 处理聊天请求的完整函数
 * @param context 请求上下文，包含会话和请求信息
 * @param body 聊天请求体，包含会话ID、请求ID、消息和配置信息
 * @returns 返回聊天消息的Promise
 */
async function completeChatRequest(
  context: RequestContext,
  body: ChatRequestBody,
): Promise<ChatMessage> {
  // 创建请求键，由会话ID和请求ID组成，使用\u0000作为分隔符
  try {
    return await context.conversationService.chat(body);
  } catch (error) {
    return mapChatRequestError(error);
  }
  /* const requestKey = `${body.sessionId}\u0000${body.requestId}`;
  // 检查是否已有已完成的请求
  const completedRequest = context.completedRequests.get(requestKey);
  if (completedRequest !== undefined) {
    // 如果存在已完成请求，验证请求消息是否匹配
    requireMatchingRequestMessage(completedRequest.requestMessage, body.message);
    // 返回已完成的响应
    return completedRequest.responseMessage;
  }

  // 检查是否已有正在处理的请求
  const existingRequest = context.inFlightRequests.get(requestKey);
  if (existingRequest !== undefined) {
    // 如果存在正在处理的请求，验证请求消息是否匹配
    requireMatchingRequestMessage(existingRequest.requestMessage, body.message);
    // 返回正在处理的响应
    return existingRequest.response;
  }

  // 创建新的待处理响应，并加入队列处理
  const pendingResponse = runQueuedChat(
    context,
    body.sessionId,
    body.message,
    body.profileId,
  ).catch(mapChatRequestError); // 捕获并映射错误
  // 将待处理响应添加到上下文中
  context.inFlightRequests.set(requestKey, {
    requestMessage: body.message,
    response: pendingResponse,
  });
  try {
    // 等待响应完成
    const message = await pendingResponse;
    // 记录已完成的请求
    rememberCompletedRequest(context.completedRequests, requestKey, body.message, message);
    // 返回响应消息
    return message;
  } finally {
    // 无论成功或失败，都从正在处理的请求中移除
    context.inFlightRequests.delete(requestKey);
  } */
}

function mapChatRequestError(error: unknown): never {
  if (error instanceof RequestConflictError) {
    throw new HttpError(409, 'REQUEST_CONFLICT', error.message);
  }
  if (error instanceof UnknownAgentProfileError) {
    throw new HttpError(400, 'UNKNOWN_PROFILE', '请求的 Agent Profile 不存在');
  }
  if (error instanceof ConversationProfileConflictError) {
    throw new HttpError(409, 'PROFILE_CONFLICT', '会话已绑定其他 Agent Profile');
  }
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
  profileId: string | undefined,
): Promise<ChatMessage> {
  const previousRequest = context.sessionQueues.get(sessionId) ?? Promise.resolve();
  let releaseQueue: (() => void) | undefined;
  const currentRequest = new Promise<void>((resolveQueue) => {
    releaseQueue = resolveQueue;
  });
  context.sessionQueues.set(sessionId, currentRequest);

  await previousRequest;
  try {
    if (context.options.profileAgent !== undefined) {
      return await context.options.profileAgent.chat(sessionId, profileId, message);
    }
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

/**
 * 主函数，启动 Stargazer Web 服务
 * @returns {Promise<number>} 返回状态码，0 表示成功，2 表示失败
 */
void runQueuedChat;
void requireMatchingRequestMessage;
void rememberCompletedRequest;

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
    const profiles = loadAgentProfiles(modelName);
    const profileAgent = new ProfileAgent({
      profiles,
      defaultProfileId: profiles[0]!.id,
      conversationStore,
      createModel: (profile) =>
        new OpenAICompatibleChatModel({
          apiKey: requireEnvironment('OPENAI_API_KEY'),
          model: profile.model,
          baseUrl: process.env.OPENAI_BASE_URL,
        }),
    });
    // 保留默认 Agent 以兼容未启用 Profile 的嵌入式 WebServer 调用。
    const agent = new ChatAgent({
      model: new OpenAICompatibleChatModel({
        apiKey: requireEnvironment('OPENAI_API_KEY'),
        model: modelName,
        baseUrl: process.env.OPENAI_BASE_URL,
      }),
      conversationStore,
      systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT,
    });
    // 创建 Web 服务器，配置代理、模型名称和存储方式
    const server = createWebServer({
      agent,
      profileAgent,
      modelName,
      conversationStorage: 'sqlite',
    });
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
 * 加载代理配置文件
 * @param defaultModel 默认使用的模型
 * @returns 返回只读的代理配置文件数组
 */
function loadAgentProfiles(defaultModel: string): readonly AgentProfile[] {
  // 从环境变量中获取原始配置字符串，并去除首尾空格
  const rawProfiles = process.env.STARGAZER_AGENT_PROFILES?.trim();
  // 如果没有配置，返回默认配置
  if (!rawProfiles) {
    return [
      {
        id: 'default',
        name: '默认助手',
        model: defaultModel,
        systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT,
      },
    ];
  }

  let value: unknown; // 用于存储解析后的值
  try {
    // 尝试解析JSON字符串
    value = JSON.parse(rawProfiles) as unknown;
  } catch {
    // 如果解析失败，抛出错误
    throw new Error('STARGAZER_AGENT_PROFILES 必须是 JSON 数组');
  }
  // 检查解析后的值是否为数组
  if (!Array.isArray(value)) {
    throw new Error('STARGAZER_AGENT_PROFILES 必须是 JSON 数组');
  }
  // 将每个数组项解析为AgentProfile对象
  return value.map((item) => parseAgentProfile(item));
}

/**
 * 解析代理档案对象的函数
 * @param value - 未知类型的输入值，期望是一个对象
 * @returns 返回一个格式化的 AgentProfile 对象
 * @throws 当输入值不符合要求时抛出错误
 */
function parseAgentProfile(value: unknown): AgentProfile {
  // 检查输入值是否为非空对象且不是数组
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Agent Profile 必须是对象');
  }
  // 将输入值断言为 Record<string, unknown> 类型
  const profile = value as Record<string, unknown>;
  // 使用 requireProfileText 函数获取必需的文本字段
  const id = requireProfileText(profile.id, 'id');
  const name = requireProfileText(profile.name, 'name');
  const model = requireProfileText(profile.model, 'model');
  // 使用 optionalProfileText 函数获取可选的文本字段
  const systemPrompt = optionalProfileText(profile.systemPrompt, 'systemPrompt');
  // 获取历史记录限制值
  const historyLimit = profile.historyLimit;
  // 验证 historyLimit 的有效性（如果存在）
  if (
    historyLimit !== undefined &&
    (typeof historyLimit !== 'number' || !Number.isSafeInteger(historyLimit) || historyLimit < 1)
  ) {
    throw new Error('Agent Profile 的 historyLimit 必须是大于零的整数');
  }
  // 返回处理后的档案对象
  return { id, name, model, systemPrompt, historyLimit };
}

function requireProfileText(value: unknown, fieldName: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`Agent Profile 的 ${fieldName} 不能为空`);
  }
  return value.trim();
}

function optionalProfileText(value: unknown, fieldName: string): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  return requireProfileText(value, fieldName);
}

/**
 * 获取并验证环境变量值
 * @param name 环境变量名称
 * @returns 环境变量的值（去除首尾空格）
 * @throws 当环境变量不存在或为空时抛出错误
 */
function requireEnvironment(name: string): string {
  const value = process.env[name]?.trim(); // 获取环境变量并去除首尾空格
  if (!value) {
    // 检查环境变量是否存在或为空
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
