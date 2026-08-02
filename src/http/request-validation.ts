/**
 * HTTP 请求体与路径参数校验，集中维护外部输入边界。
 *
 * 这里返回的值已经完成空白裁剪和长度限制，应用层可以将其视为可信命令对象。
 */

import { HttpError } from './http-error.js';

export interface ChatRequestBody {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string | undefined;
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

/**
 * 标识符用于会话、请求和 Profile 的索引，因此限制为 URL 与存储均可安全处理的字符集。
 */
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
