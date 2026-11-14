"""兼容服务可以省略 DONE；仅接受有效结束原因后的干净传输结尾。"""

from typing import cast

import httpx
import pytest

from dokkan_agent.domain.agent.errors import ModelUnavailableError
from dokkan_agent.domain.agent.models import ModelCompleted, ModelRequest, UsageReported
from dokkan_agent.infrastructure.provider.openai_compatible import (
    OpenAICompatibleGateway,
    ProviderOptions,
)
from dokkan_agent.infrastructure.provider.sse_reader import read_sse_data


async def test_clean_eof_after_finish_keeps_trailing_usage() -> None:
    content = (
        'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":1,"total_tokens":3}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, text=content)
        return response

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, trust_env=False)
    options = ProviderOptions("https://test/v1", "test-key")
    request = ModelRequest("test", ())
    async with client:
        gateway = OpenAICompatibleGateway(client, options)
        stream = gateway.stream(request)
        events = [event async for event in stream]
    expected = ModelCompleted("stop")
    assert events[-1] == expected
    usage_event = events[-2]
    is_usage = isinstance(usage_event, UsageReported)
    assert is_usage
    usage_event = cast(UsageReported, usage_event)
    usage = usage_event.usage
    assert usage.total_tokens == 3


async def test_sse_comments_multiline_and_crlf() -> None:
    content = b': heartbeat\r\ndata: {"choices":\r\ndata: []}\r\n\r\n'
    response = httpx.Response(200, content=content)
    stream = read_sse_data(response)
    events = [event async for event in stream]
    assert events == ['{"choices":\n[]}']


async def test_event_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dokkan_agent.infrastructure.provider.sse_reader.MAX_EVENT_CHARACTERS", 8)
    response = httpx.Response(200, content=b"data: too long\n\n")
    stream = read_sse_data(response)
    failure = pytest.raises(ModelUnavailableError)
    with failure:
        _ = [event async for event in stream]


async def test_stream_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dokkan_agent.infrastructure.provider.sse_reader.MAX_STREAM_BYTES", 8)
    response = httpx.Response(200, content=b"data: too long\n\n")
    stream = read_sse_data(response)
    failure = pytest.raises(ModelUnavailableError)
    with failure:
        _ = [event async for event in stream]
