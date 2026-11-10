"""输入协议校验：先限制字节再解析 JSON，避免框架默认 422 和原始输入泄露。"""

from fastapi import Request
from pydantic import ValidationError

from dokkan_agent.interfaces.http.error_mapper import ApiError
from dokkan_agent.interfaces.http.errors import ErrorCode
from dokkan_agent.interfaces.http.schemas import ChatRequest, SessionQuery

MAX_BODY_BYTES = 32 * 1024


async def read_chat_request(request: Request) -> ChatRequest:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ApiError(
            415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Content-Type 必须为 application/json。"
        )
    length = request.headers.get("content-length")
    if length:
        try:
            declared = int(length)
            if declared < 0:
                raise ValueError
        except ValueError:
            raise ApiError(400, ErrorCode.INVALID_REQUEST, "请求长度无效。") from None
        if declared > MAX_BODY_BYTES:
            raise ApiError(413, ErrorCode.REQUEST_TOO_LARGE, "请求体超过 32 KiB。")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            raise ApiError(413, ErrorCode.REQUEST_TOO_LARGE, "请求体超过 32 KiB。")
        body.extend(chunk)
    try:
        return ChatRequest.model_validate_json(body)
    except (ValidationError, ValueError):
        raise ApiError(400, ErrorCode.INVALID_REQUEST, "聊天请求格式或字段无效。") from None


def read_session_query(request: Request) -> SessionQuery:
    try:
        if len(request.query_params.getlist("sessionId")) != 1:
            raise ValueError
        return SessionQuery.model_validate({"sessionId": request.query_params.get("sessionId")})
    except (ValidationError, ValueError):
        raise ApiError(400, ErrorCode.INVALID_REQUEST, "sessionId 无效。") from None
