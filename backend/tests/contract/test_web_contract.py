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
    body = {'sessionId': ' session_1 ', 'requestId': 'r1', 'message': '\ufeff 你好 \ufeff'}
    validated_request = ChatRequest.model_validate(body)
    command = validated_request.to_command()
    validated_request_2 = ChatRequest.model_validate(body | {'ignored': True})
    same = validated_request_2.to_command()
    validated_request_3 = ChatRequest.model_validate(body | {'profileId': 'other'})
    switched = validated_request_3.to_command()
    assert command.session_id == 'session_1'
    assert command.message == '你好'
    fingerprint = command.fingerprint()
    fingerprint_2 = same.fingerprint()
    assert fingerprint == fingerprint_2
    fingerprint_3 = command.fingerprint()
    fingerprint_4 = switched.fingerprint()
    assert fingerprint_3 != fingerprint_4
    fingerprint_5 = command.fingerprint()
    startswith = fingerprint_5.startswith('v1:')
    assert startswith


@pytest.mark.parametrize('field,value', [('sessionId', '../other'), ('sessionId', 'a' * 129), ('requestId', None), ('message', ' '), ('message', 123), ('profileId', None), ('profileId', '')])
def test_invalid_chat_fields_are_rejected(field: str, value: object) -> None:
    body = {'sessionId': 's1', 'requestId': 'r1', 'message': '你好'}
    expected_error = pytest.raises(ValidationError)
    with expected_error:
        ChatRequest.model_validate(body | {field: value})


def test_message_limit_counts_utf16_units_like_existing_web() -> None:
    body = {'sessionId': 's1', 'requestId': 'r1', 'message': '😀' * 8000}
    validated_request = ChatRequest.model_validate(body)
    item_count = len(validated_request.message)
    assert item_count == 8000
    expected_error = pytest.raises(ValidationError)
    with expected_error:
        ChatRequest.model_validate(body | {'message': '😀' * 8001})


def test_reply_serialization_preserves_metadata_and_omits_unknown_counts() -> None:
    token_usage = TokenUsage(input_tokens=3, total_tokens=9)
    reply = AssistantReply('回答', '公开的推理摘要', token_usage)
    reply_response = MessageResponse.from_reply(reply)
    payload = reply_response.model_dump(by_alias=True, exclude_none=True)
    assert payload == {'role': 'assistant', 'content': '回答', 'reasoning': '公开的推理摘要', 'usage': {'inputTokens': 3, 'totalTokens': 9}}
    validated_request = MessageResponse.model_validate(payload)
    serialized_response = validated_request.model_dump(by_alias=True, exclude_none=True)
    assert serialized_response == payload


def test_user_cannot_carry_assistant_metadata() -> None:
    expected_error = pytest.raises(ValidationError)
    with expected_error:
        token_usage_response = TokenUsageResponse(input_tokens=1)
        MessageResponse(role='user', content='消息', usage=token_usage_response)


def test_sse_wire_examples_match_dtos(project_root: Path) -> None:
    reasoning_event = ReasoningEvent(content='公开推理摘要')
    chunk_event = ChunkEvent(content='第一行\n第二行')
    token_usage_response = TokenUsageResponse(input_tokens=3, output_tokens=6, total_tokens=9)
    usage_event = UsageEvent(usage=token_usage_response)
    done_event = DoneEvent()
    events: list[SseEvent] = [reasoning_event, chunk_event, usage_event, done_event]
    encoded_events = []
    for event in events:
        encoded_event = encode_event(event)
        encoded_events.append(encoded_event)
    value = b''
    wire = value.join(encoded_events)
    expected = project_root / 'backend/docs/examples/success.sse'
    decode = wire.decode()
    replace = decode.replace('\r\n', '\n')
    document_text = expected.read_text(encoding='utf-8')
    assert replace == document_text
    split = wire.split(b'\n\n')
    item_count = len(split)
    assert item_count == 5
    error_event = ErrorEvent(code=ErrorCode.MODEL_UNAVAILABLE, message='模型暂时不可用。')
    error = encode_event(error_event)
    startswith = error.startswith(b'event: error\n')
    assert startswith
    decode_2 = error.decode()
    split_2 = decode_2.split('data: ')
    parsed_payload = json.loads(split_2[1])
    assert parsed_payload['code'] == 'MODEL_UNAVAILABLE'
