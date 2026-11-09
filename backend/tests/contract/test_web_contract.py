"""冻结 Web 字段、Unicode 边界、重放元数据与 SSE 编码。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dokkan_agent.domain.agent.models import TokenUsage
from dokkan_agent.domain.conversation.models import AssistantReply
from dokkan_agent.interfaces.http.errors import ErrorCode
from dokkan_agent.interfaces.http.schemas import ChatRequest, MessageResponse, TokenUsageResponse
from dokkan_agent.interfaces.http.sse import (
    ChunkEvent,
    DoneEvent,
    ErrorEvent,
    ReasoningEvent,
    SseEvent,
    UsageEvent,
    encode_event,
)


def test_request_normalization_preserves_explicit_model_in_fingerprint() -> None:
    body = {"sessionId": " session_1 ", "requestId": "r1", "message": "\ufeff 你好 \ufeff"}
    command = ChatRequest.model_validate(body).to_command()
    same = ChatRequest.model_validate(body | {"ignored": True}).to_command()
    switched = ChatRequest.model_validate(body | {"profileId": "other"}).to_command()
    assert command.session_id == "session_1"
    assert command.message == "你好"
    assert command.fingerprint() == same.fingerprint()
    assert command.fingerprint() != switched.fingerprint()
    assert command.fingerprint().startswith("v1:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("sessionId", "../other"),
        ("sessionId", "a" * 129),
        ("requestId", None),
        ("message", " "),
        ("message", 123),
        ("profileId", None),
        ("profileId", ""),
    ],
)
def test_invalid_chat_fields_are_rejected(field: str, value: object) -> None:
    body = {"sessionId": "s1", "requestId": "r1", "message": "你好"}
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body | {field: value})


def test_message_limit_counts_utf16_units_like_existing_web() -> None:
    body = {"sessionId": "s1", "requestId": "r1", "message": "😀" * 8000}
    assert len(ChatRequest.model_validate(body).message) == 8000
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(body | {"message": "😀" * 8001})


def test_reply_serialization_preserves_metadata_and_omits_unknown_counts() -> None:
    reply = AssistantReply("回答", "公开的推理摘要", TokenUsage(input_tokens=3, total_tokens=9))
    payload = MessageResponse.from_reply(reply).model_dump(by_alias=True, exclude_none=True)
    assert payload == {
        "role": "assistant",
        "content": "回答",
        "reasoning": "公开的推理摘要",
        "usage": {"inputTokens": 3, "totalTokens": 9},
    }
    assert (
        MessageResponse.model_validate(payload).model_dump(by_alias=True, exclude_none=True)
        == payload
    )


def test_user_cannot_carry_assistant_metadata() -> None:
    with pytest.raises(ValidationError):
        MessageResponse(role="user", content="消息", usage=TokenUsageResponse(input_tokens=1))


def test_sse_wire_examples_match_dtos(project_root: Path) -> None:
    events: list[SseEvent] = [
        ReasoningEvent(content="公开推理摘要"),
        ChunkEvent(content="第一行\n第二行"),
        UsageEvent(usage=TokenUsageResponse(input_tokens=3, output_tokens=6, total_tokens=9)),
        DoneEvent(),
    ]
    wire = b"".join(encode_event(event) for event in events)
    expected = project_root / "backend/docs/examples/success.sse"
    assert wire.decode().replace("\r\n", "\n") == expected.read_text(encoding="utf-8")
    assert len(wire.split(b"\n\n")) == 5
    error = encode_event(ErrorEvent(code=ErrorCode.MODEL_UNAVAILABLE, message="模型暂时不可用。"))
    assert error.startswith(b"event: error\n")
    assert json.loads(error.decode().split("data: ")[1])["code"] == "MODEL_UNAVAILABLE"
