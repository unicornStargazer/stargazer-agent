"""使用真实 HTTPX 解码路径和可控字节流，不访问网络或真实密钥。"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from dokkan_agent.domain.agent.errors import ModelCapabilityError, ModelUnavailableError
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    MessageRole,
    ModelCompleted,
    ModelMessage,
    ModelRequest,
    ReasoningDelta,
    ToolCallReady,
    UsageReported,
)
from dokkan_agent.domain.tool.models import ToolDefinition
from dokkan_agent.infrastructure.provider.openai_compatible import (
    OpenAICompatibleGateway,
    ProviderOptions,
)


def frame(payload: object) -> bytes:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {content}\r\n\r\n".encode()


def delta(content: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": content, "finish_reason": finish}]}


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes, failure: bool = False) -> None:
        self.payload = payload
        self.failure = failure
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        # 按单字节打碎，确保 UTF-8 多字节字符和 CRLF 都跨传输边界。
        for value in self.payload:
            yield bytes([value])
        if self.failure:
            raise httpx.ReadTimeout("测试超时")

    async def aclose(self) -> None:
        self.closed = True


def request_with_tools() -> ModelRequest:
    return ModelRequest(
        "test",
        (ModelMessage(MessageRole.USER, "测试"),),
        (ToolDefinition("echo", "测试", {"type": "object"}),),
    )


async def test_fragmented_tools_and_usage_after_finish() -> None:
    stream = ByteStream(
        b"".join(
            [
                frame(delta({"reasoning_content": "公开摘要"})),
                frame(delta({"content": "先检查"})),
                frame(
                    delta(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "type": "function",
                                    "function": {"name": "ec", "arguments": '{"text":'},
                                },
                                {
                                    "index": 1,
                                    "id": "b",
                                    "function": {"name": "echo", "arguments": "{}"},
                                },
                            ]
                        }
                    )
                ),
                frame(
                    delta(
                        {
                            "tool_calls": [
                                {"index": 0, "function": {"name": "ho", "arguments": '"中文"}'}}
                            ]
                        }
                    )
                ),
                frame(delta({}, "tool_calls")),
                frame(
                    {
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 4,
                            "completion_tokens": 7,
                            "total_tokens": 11,
                            "completion_tokens_details": {"reasoning_tokens": 2},
                        },
                    }
                ),
                frame("[DONE]"),
            ]
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    ) as client:
        gateway = OpenAICompatibleGateway(client, ProviderOptions("https://test/v1", "test-key"))
        events = [event async for event in gateway.stream(request_with_tools())]
    assert events[0] == ReasoningDelta("公开摘要")
    assert events[1] == ContentDelta("先检查")
    calls = [event.call for event in events if isinstance(event, ToolCallReady)]
    assert [(call.id, call.name, json.loads(call.arguments)) for call in calls] == [
        ("a", "echo", {"text": "中文"}),
        ("b", "echo", {}),
    ]
    assert isinstance(events[2], UsageReported)
    assert events[2].usage.total_tokens == 11
    assert events[-1] == ModelCompleted("tool_calls")
    assert stream.closed


@pytest.mark.parametrize(
    "payload",
    [
        frame(delta({"content": "partial"})),
        frame("not-json"),
        frame(delta({})),  # 正常 EOF 仍必须有结束原因。
        frame(
            delta(
                {"tool_calls": [{"index": 0, "function": {"name": "echo", "arguments": "{"}}]},
                "tool_calls",
            )
        )
        + frame("[DONE]"),
        frame(delta({}, "stop")) + frame(delta({"content": "late"})) + frame("[DONE]"),
        frame(delta({}, "stop"))
        + frame({"choices": [], "usage": {"prompt_tokens": True}})
        + frame("[DONE]"),
    ],
)
async def test_invalid_or_truncated_stream_never_completes(payload: bytes) -> None:
    stream = ByteStream(payload)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    ) as client:
        gateway = OpenAICompatibleGateway(client, ProviderOptions("https://test/v1", "test-key"))
        with pytest.raises(ModelUnavailableError):
            _ = [event async for event in gateway.stream(request_with_tools())]
    assert stream.closed


async def test_transient_status_retries_before_output_only() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=frame(delta({"content": "ok"}, "stop")) + frame("[DONE]"),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in OpenAICompatibleGateway(
                client, ProviderOptions("https://test/v1", "test-key")
            ).stream(request_with_tools())
        ]
    assert attempts == 2
    assert events[-1] == ModelCompleted("stop")


async def test_read_timeout_after_visible_output_never_retries() -> None:
    attempts = 0
    stream = ByteStream(frame(delta({"content": "partial"})), failure=True)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = OpenAICompatibleGateway(
            client, ProviderOptions("https://test/v1", "test-key")
        ).stream(request_with_tools())
        assert await anext(events) == ContentDelta("partial")
        with pytest.raises(ModelUnavailableError):
            await anext(events)
    assert attempts == 1
    assert stream.closed


async def test_close_propagates_to_response() -> None:
    stream = ByteStream(frame(delta({"content": "partial"})))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    ) as client:
        events = OpenAICompatibleGateway(
            client, ProviderOptions("https://test/v1", "test-key")
        ).stream(request_with_tools())
        await anext(events)
        await events.aclose()
    assert stream.closed


async def test_tools_unsupported_does_not_fall_back() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": {"param": "tools", "message": "test-secret"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OpenAICompatibleGateway(client, ProviderOptions("https://test/v1", "test-key"))
        with pytest.raises(ModelCapabilityError) as captured:
            _ = [event async for event in gateway.stream(request_with_tools())]
    assert attempts == 1
    assert "test-secret" not in str(captured.value)
