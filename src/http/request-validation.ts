/** HTTP 请求体和路径参数校验，集中维护外部输入边界。 */

import { HttpError } from './http-error.js';

export interface ChatRequestBody {
  readonly sessionId: string;
  readonly requestId: string;
  readonly message: string;
  readonly profileId: string | undefined;
}

/**
 * 验证聊天请求的数据格式和内容
 * @param value - 未知类型的输入值，将被验证为聊天请求体
 * @param maximumMessageLength - 消息的最大允许长度
 * @param maximumIdentifierLength - 标识符的最大允许长度
 * @returns 返回经过验证和格式化的 ChatRequestBody 对象
 * @throws 当请求不符合要求时抛出 HttpError
 */
export function validateChatRequest(
  value: unknown, // 输入的未知类型值，需要进行验证
  maximumMessageLength: number, // 消息的最大长度限制
  maximumIdentifierLength: number, // 标识符的最大长度限制
): ChatRequestBody { // 函数返回类型为 ChatRequestBody
  // 检查输入值是否为非空对象且不是数组
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new HttpError(400, 'INVALID_REQUEST', '请求内容必须是 JSON 对象。');
  }
  const body = value as Record<string, unknown>; // 将输入值断言为记录对象
  return {
    sessionId: requireIdentifier(body.sessionId, 'sessionId', maximumIdentifierLength), // 验证并获取会话ID
    requestId: requireIdentifier(body.requestId, 'requestId', maximumIdentifierLength), // 验证并获取请求ID
    message: requireText(body.message, 'message', maximumMessageLength), // 验证并获取消息内容
    profileId: // 处理可选的配置文件ID
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
