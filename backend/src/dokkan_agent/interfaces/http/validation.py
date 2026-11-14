"""输入协议校验：先限制字节再解析 JSON，避免框架默认 422 和原始输入泄露。"""

from fastapi import Request
from pydantic import ValidationError

from dokkan_agent.interfaces.http.error_mapper import ApiError
from dokkan_agent.interfaces.http.errors import ErrorCode
from dokkan_agent.interfaces.http.schemas import ChatRequest, SessionQuery

MAX_BODY_BYTES = 32 * 1024


async def read_chat_request(request: Request) -> ChatRequest:
    headers = request.headers
    content_type = headers.get("content-type", "")
    media_parts = content_type.split(";", 1)
    stripped_media_type = media_parts[0].strip()
    media_type = stripped_media_type.lower()
    if media_type != "application/json":
        raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Content-Type 必须为 application/json。")
    length = headers.get("content-length")
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
    stream = request.stream()
    async for chunk in stream:
        body_size = len(body)
        chunk_size = len(chunk)
        if body_size + chunk_size > MAX_BODY_BYTES:
            raise ApiError(413, ErrorCode.REQUEST_TOO_LARGE, "请求体超过 32 KiB。")
        body.extend(chunk)
    try:
        chat_request = ChatRequest.model_validate_json(body)
        return chat_request
    except (ValidationError, ValueError):
        raise ApiError(400, ErrorCode.INVALID_REQUEST, "聊天请求格式或字段无效。") from None


def read_session_query(request: Request) -> SessionQuery:
    try:
        query_params = request.query_params
        session_ids = query_params.getlist("sessionId")
        session_count = len(session_ids)
        if session_count != 1:
            raise ValueError
        session_id = query_params.get("sessionId")
        query = SessionQuery.model_validate({"sessionId": session_id})
        return query
    except (ValidationError, ValueError):
        raise ApiError(400, ErrorCode.INVALID_REQUEST, "sessionId 无效。") from None
