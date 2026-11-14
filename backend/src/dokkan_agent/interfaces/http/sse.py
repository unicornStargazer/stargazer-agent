"""SSE 纯编码器；不管理模型流、数据库事务或客户端连接。"""

from typing import ClassVar

from dokkan_agent.interfaces.http.errors import ErrorDetail
from dokkan_agent.interfaces.http.schemas import HttpModel, TokenUsageResponse


class ChunkEvent(HttpModel):
    event_name: ClassVar[str] = "chunk"
    content: str


class ReasoningEvent(HttpModel):
    event_name: ClassVar[str] = "reasoning"
    content: str


class UsageEvent(HttpModel):
    event_name: ClassVar[str] = "usage"
    usage: TokenUsageResponse


class DoneEvent(HttpModel):
    """只能在完整轮次和请求结果事务提交后发送；不能表示一次模型调用结束。"""

    event_name: ClassVar[str] = "done"


class ErrorEvent(ErrorDetail):
    event_name: ClassVar[str] = "error"


type SseEvent = ChunkEvent | ReasoningEvent | UsageEvent | DoneEvent | ErrorEvent


def encode_event(event: SseEvent) -> bytes:
    """JSON 转义正文中的换行，防止文字被误识别为新的 SSE 事件。"""
    payload = event.model_dump_json(by_alias=True, exclude_none=True)
    frame = f"event: {event.event_name}\ndata: {payload}\n\n"
    encoded = frame.encode()
    return encoded
