"""薄 HTTP 路由：只做 DTO 转换和协议事件映射，会话事务交给应用服务。"""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import cast

from fastapi import APIRouter, Request

from dokkan_agent.application.conversation.service import PreparedConversation
from dokkan_agent.domain.agent.models import ContentDelta, ReasoningDelta, UsageReported
from dokkan_agent.domain.conversation.models import AssistantReply
from dokkan_agent.interfaces.http.error_mapper import map_error
from dokkan_agent.interfaces.http.schemas import (
    ChatResponse,
    DeleteHistoryResponse,
    HistoryResponse,
    MessageResponse,
    ProfilesResponse,
    StatusResponse,
    TokenUsageResponse,
)
from dokkan_agent.interfaces.http.services import get_services
from dokkan_agent.interfaces.http.sse import (
    ChunkEvent,
    DoneEvent,
    ErrorEvent,
    ReasoningEvent,
    UsageEvent,
    encode_event,
)
from dokkan_agent.interfaces.http.streaming_response import (
    ConversationStreamingResponse,
    until_disconnect,
)
from dokkan_agent.interfaces.http.validation import read_chat_request, read_session_query

router = APIRouter(prefix="/api")


@router.get("/status", response_model=StatusResponse, response_model_exclude_none=True)
async def status(request: Request) -> StatusResponse:
    services = get_services(request)
    response = StatusResponse(ready=True, model=services.default_profile.model, conversation_storage="sqlite", default_profile=services.default_profile)
    return response


@router.get("/profiles", response_model=ProfilesResponse, response_model_exclude_none=True)
async def profiles(request: Request) -> ProfilesResponse:
    services = get_services(request)
    available = list(services.profiles)
    response = ProfilesResponse(profiles=available)
    return response


@router.get("/history", response_model=HistoryResponse, response_model_exclude_none=True)
async def history(request: Request) -> HistoryResponse:
    query = read_session_query(request)
    services = get_services(request)
    conversations = services.conversations
    messages = await conversations.history(query.session_id)
    responses: list[MessageResponse] = []
    for message in messages:
        if message.reply:
            response_message = MessageResponse.from_reply(message.reply)
        else:
            response_message = MessageResponse(role="user", content=message.content)
        responses.append(response_message)
    response = HistoryResponse(messages=responses)
    return response


@router.delete("/history", response_model=DeleteHistoryResponse, response_model_exclude_none=True)
async def delete_history(request: Request) -> DeleteHistoryResponse:
    query = read_session_query(request)
    services = get_services(request)
    conversations = services.conversations
    await conversations.delete(query.session_id)
    response = DeleteHistoryResponse()
    return response


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat(request: Request) -> ChatResponse:
    body = await read_chat_request(request)
    services = get_services(request)
    conversations = services.conversations
    command = body.to_command()
    operation = conversations.chat(command)
    reply = await until_disconnect(request, operation)
    message = MessageResponse.from_reply(reply)
    response = ChatResponse(message=message)
    return response


@router.post("/chat/stream")
async def stream_chat(request: Request) -> ConversationStreamingResponse:
    body = await read_chat_request(request)
    services = get_services(request)
    conversations = services.conversations
    command = body.to_command()
    operation = conversations.prepare(command)
    prepared = await until_disconnect(request, operation, PreparedConversation.aclose)
    events = _stream_events(prepared)
    response = ConversationStreamingResponse(events, prepared)
    return response


async def _stream_events(prepared: PreparedConversation) -> AsyncGenerator[bytes, None]:
    try:
        stream = prepared.stream()
        stream_context = aclosing(stream)
        async with stream_context as events:
            async for event in events:
                is_content = isinstance(event, ContentDelta)
                if is_content:
                    content_delta = cast(ContentDelta, event)
                    chunk_event = ChunkEvent(content=content_delta.content)
                    encoded = encode_event(chunk_event)
                    yield encoded
                    continue
                is_reasoning = isinstance(event, ReasoningDelta)
                if is_reasoning:
                    reasoning_delta = cast(ReasoningDelta, event)
                    reasoning_event = ReasoningEvent(content=reasoning_delta.content)
                    encoded = encode_event(reasoning_event)
                    yield encoded
                    continue
                is_usage = isinstance(event, UsageReported)
                if is_usage:
                    usage_report = cast(UsageReported, event)
                    usage = usage_report.usage
                    usage_response = TokenUsageResponse(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, reasoning_tokens=usage.reasoning_tokens, total_tokens=usage.total_tokens)
                    usage_event = UsageEvent(usage=usage_response)
                    encoded = encode_event(usage_event)
                    yield encoded
                    continue
                is_reply = isinstance(event, AssistantReply)
                if is_reply:
                    done_event = DoneEvent()
                    encoded = encode_event(done_event)
                    yield encoded
    except Exception as error:
        mapped = map_error(error)
        error_event = ErrorEvent(code=mapped.code, message=mapped.message)
        encoded = encode_event(error_event)
        yield encoded
