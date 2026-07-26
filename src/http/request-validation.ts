/** HTTP 请求体和路径参数校验，集中维护外部输入边界。 */

import type { IncomingMessage } from 'node:http';

import { HttpError } from './http-error.js';

export interface ChatRequestBody {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string | undefined;
}

export async function readJsonBody(
  request: IncomingMessage,
  maximumBytes: number,
): Promise<unknown> {
  const contentType = request.headers['content-type'] ?? '';
  if (contentType.split(';', 1).at(0)?.trim().toLowerCase() !== 'application/json') {
    throw new HttpError(415, 'UNSUPPORTED_MEDIA_TYPE', '请求必须使用 application/json。');
  }
  const declaredLength = Number(request.headers['content-length'] ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    throw new HttpError(413, 'REQUEST_TOO_LARGE', '请求内容过大。');
  }
  const chunks: Buffer[] = [];
  let byteLength = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk as Uint8Array);
    byteLength += buffer.byteLength;
    if (byteLength > maximumBytes) {
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

export function validateChatRequest(
  value: unknown,
  maximumMessageLength: number,
  maximumIdentifierLength: number,
): ChatRequestBody {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new HttpError(400, 'INVALID_REQUEST', '请求内容必须是 JSON 对象。');
  }
  const body = value as Record<string, unknown>;
  return {
    sessionId: requireIdentifier(body.sessionId, 'sessionId', maximumIdentifierLength),
    requestId: requireIdentifier(body.requestId, 'requestId', maximumIdentifierLength),
    message: requireText(body.message, 'message', maximumMessageLength),
    profileId:
      body.profileId === undefined
        ? undefined
        : requireIdentifier(body.profileId, 'profileId', maximumIdentifierLength),
  };
}

export function requireIdentifier(
  value: unknown,
  fieldName: string,
  maximumLength: number,
): string {
  const identifier = requireText(value, fieldName, maximumLength);
  if (!/^[a-zA-Z0-9_-]+$/.test(identifier)) {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 格式不正确。`);
  }
  return identifier;
}

export function requireMethod(request: IncomingMessage, expectedMethod: string): void {
  if (request.method !== expectedMethod) {
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该接口不支持当前请求方法。');
  }
}

function requireText(value: unknown, fieldName: string, maximumLength: number): string {
  if (typeof value !== 'string')
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 必须是字符串。`);
  const normalizedValue = value.trim();
  if (!normalizedValue) throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 不能为空。`);
  if (normalizedValue.length > maximumLength) {
    throw new HttpError(400, 'INVALID_REQUEST', `${fieldName} 超出长度限制。`);
  }
  return normalizedValue;
}
