/** 将领域、基础设施和 Fastify 异常收敛为稳定的 HTTP 错误契约。 */

import type { FastifyInstance } from 'fastify';

import { RequestConflictError, SessionBusyError } from '../application/conversation-service.js';
import { ConversationStoreError } from '../chat/index.js';
import { ConversationProfileConflictError, UnknownAgentProfileError } from '../profiles/index.js';
import { HttpError } from './http-error.js';

export function registerErrorHandler(app: FastifyInstance): void {
  app.setErrorHandler((error, _request, reply) => {
    const mappedError = mapHttpError(error);
    void reply
      .code(mappedError.status)
      .type('application/json; charset=utf-8')
      .send({ error: { code: mappedError.code, message: mappedError.message } });
  });
}

export function mapHttpError(error: unknown): HttpError {
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
    return new HttpError(400, 'UNKNOWN_PROFILE', '请求的 Agent Profile 不存在。');
  }
  if (error instanceof ConversationProfileConflictError) {
    return new HttpError(409, 'PROFILE_CONFLICT', '会话已绑定其他 Agent Profile。');
  }
  if (error instanceof ConversationStoreError) {
    return new HttpError(
      503,
      'CONVERSATION_STORAGE_UNAVAILABLE',
      '会话存储暂时不可用，请稍后重试。',
    );
  }
  return (
    mapFastifyError(error) ??
    new HttpError(502, 'MODEL_UNAVAILABLE', '模型暂时不可用，请稍后重试。')
  );
}

function mapFastifyError(error: unknown): HttpError | undefined {
  switch (fastifyErrorCode(error)) {
    case 'FST_ERR_CTP_BODY_TOO_LARGE':
      return new HttpError(413, 'REQUEST_TOO_LARGE', '请求内容过大。');
    case 'FST_ERR_CTP_INVALID_MEDIA_TYPE':
      return new HttpError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Content-Type 必须为 application/json。');
    case 'FST_ERR_CTP_INVALID_JSON':
      return new HttpError(400, 'INVALID_REQUEST', '请求内容必须是 JSON 对象。');
    default:
      return undefined;
  }
}

function fastifyErrorCode(error: unknown): string | undefined {
  if (!(error instanceof Error) || !('code' in error)) {
    return undefined;
  }
  const { code } = error as { readonly code?: unknown };
  return typeof code === 'string' ? code : undefined;
}
