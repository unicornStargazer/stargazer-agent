"""薄 HTTP 路由：只做 DTO 转换和协议事件映射，会话事务交给应用服务。"""

from collections.abc import AsyncGenerator
from contextlib import aclosing

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
    return StatusResponse(
        ready=True,
        model=services.default_profile.model,
        conversation_storage="sqlite",
        default_profile=services.default_profile,
    )


@router.get("/profiles", response_model=ProfilesResponse, response_model_exclude_none=True)
async def profiles(request: Request) -> ProfilesResponse:
    return ProfilesResponse(profiles=list(get_services(request).profiles))


@router.get("/history", response_model=HistoryResponse, response_model_exclude_none=True)
async def history(request: Request) -> HistoryResponse:
    query = read_session_query(request)
    messages = await get_services(request).conversations.history(query.session_id)
    return HistoryResponse(
        messages=[
            MessageResponse.from_reply(message.reply)
            if message.reply
            else MessageResponse(role="user", content=message.content)
            for message in messages
        ]
    )


@router.delete("/history", response_model=DeleteHistoryResponse, response_model_exclude_none=True)
async def delete_history(request: Request) -> DeleteHistoryResponse:
    query = read_session_query(request)
    await get_services(request).conversations.delete(query.session_id)
    return DeleteHistoryResponse()


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat(request: Request) -> ChatResponse:
    body = await read_chat_request(request)
    reply = await until_disconnect(
        request, get_services(request).conversations.chat(body.to_command())
    )
    return ChatResponse(message=MessageResponse.from_reply(reply))


@router.post("/chat/stream")
async def stream_chat(request: Request) -> ConversationStreamingResponse:
    body = await read_chat_request(request)
    prepared = await until_disconnect(
        request,
        get_services(request).conversations.prepare(body.to_command()),
        PreparedConversation.aclose,
    )
    return ConversationStreamingResponse(_stream_events(prepared), prepared)


async def _stream_events(prepared: PreparedConversation) -> AsyncGenerator[bytes, None]:
    try:
        async with aclosing(prepared.stream()) as events:
            async for event in events:
                if isinstance(event, ContentDelta):
                    yield encode_event(ChunkEvent(content=event.content))
                elif isinstance(event, ReasoningDelta):
                    yield encode_event(ReasoningEvent(content=event.content))
                elif isinstance(event, UsageReported):
                    usage = event.usage
                    yield encode_event(
                        UsageEvent(
                            usage=TokenUsageResponse(
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                reasoning_tokens=usage.reasoning_tokens,
                                total_tokens=usage.total_tokens,
                            )
                        )
                    )
                elif isinstance(event, AssistantReply):
                    yield encode_event(DoneEvent())
    except Exception as error:
        mapped = map_error(error)
        yield encode_event(ErrorEvent(code=mapped.code, message=mapped.message))
