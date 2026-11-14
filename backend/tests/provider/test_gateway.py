"""通过 HTTPX MockTransport 走官方 SDK 请求路径；不访问模型网络。"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import httpx
import pytest

from dokkan_agent.domain.agent.errors import ModelCapabilityError, ModelUnavailableError
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    MessageRole,
    ModelCompleted,
    ModelEvent,
    ModelMessage,
    ModelRequest,
    ReasoningDelta,
    ToolCallReady,
    UsageReported,
)
from dokkan_agent.domain.tool.models import ToolCall, ToolDefinition
from dokkan_agent.infrastructure.provider.openai_compatible import (
    OpenAICompatibleGateway,
    ProviderOptions,
)


def frame(payload: object) -> bytes:
    is_text = isinstance(payload, str)
    if is_text:
        content = cast(str, payload)
    else:
        content = json.dumps(payload, ensure_ascii=False)
    text = f"data: {content}\r\n\r\n"
    result = text.encode()
    return result


def delta(content: dict[str, Any], finish: str | None = None) -> bytes:
    payload = {"choices": [{"index": 0, "delta": content, "finish_reason": finish}]}
    result = frame(payload)
    return result


def packet(*parts: bytes) -> bytes:
    result = b"".join(parts)
    return result


class ByteStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes, failure: bool = False) -> None:
        self.payload = payload
        self.failure = failure
        self.closed = False
        self.requests: list[httpx.Request] = []

    async def __aiter__(self) -> AsyncIterator[bytes]:
        # 单字节打碎，确保中文 UTF-8 和 CRLF 都跨传输边界。
        for value in self.payload:
            chunk = bytes([value])
            yield chunk
        if self.failure:
            raise httpx.ReadTimeout("测试超时")

    async def aclose(self) -> None:
        self.closed = True

    def respond(self, request: httpx.Request) -> httpx.Response:
        requests = self.requests
        requests.append(request)
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=self)
        return response


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    timeout = httpx.Timeout(17, connect=3, write=5, pool=7)
    client = httpx.AsyncClient(transport=transport, timeout=timeout, trust_env=False)
    return client


def gateway_for(client: httpx.AsyncClient, attempts: int = 2) -> OpenAICompatibleGateway:
    options = ProviderOptions("https://test/v1", "test-key", max_attempts=attempts)
    gateway = OpenAICompatibleGateway(client, options)
    return gateway


def request_with_tools() -> ModelRequest:
    message = ModelMessage(MessageRole.USER, "测试")
    tool = ToolDefinition("echo", "测试", {"type": "object"})
    request = ModelRequest("test", (message,), (tool,))
    return request


async def collect(gateway: OpenAICompatibleGateway, request: ModelRequest) -> list[ModelEvent]:
    stream = gateway.stream(request)
    events = [event async for event in stream]
    return events


async def test_fragmented_tools_and_usage_after_finish() -> None:
    reasoning = delta({"reasoning_content": "公开摘要"})
    content = delta({"content": "先检查"})
    first_call = {"index": 0, "id": "a", "type": "function"}
    first_call["function"] = {"name": "ec", "arguments": '{"text":'}
    second_call = {"index": 1, "id": "b", "function": {"name": "echo", "arguments": "{}"}}
    first_tools = delta({"tool_calls": [first_call, second_call]})
    fragment = {"index": 0, "function": {"name": "ho", "arguments": '"中文"}'}}
    last_tools = delta({"tool_calls": [fragment]})
    finish = delta({}, "tool_calls")
    usage: dict[str, Any] = {"prompt_tokens": 4, "completion_tokens": 7, "total_tokens": 11}
    usage["completion_tokens_details"] = {"reasoning_tokens": 2}
    usage_frame = frame({"choices": [], "usage": usage})
    done = frame("[DONE]")
    payload = packet(reasoning, content, first_tools, last_tools, finish, usage_frame, done)
    stream = ByteStream(payload)
    client = client_for(stream.respond)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = await collect(gateway, request)
    expected_reasoning = ReasoningDelta("公开摘要")
    expected_content = ContentDelta("先检查")
    assert events[0] == expected_reasoning
    assert events[1] == expected_content
    calls = []
    for event in events:
        is_tool = isinstance(event, ToolCallReady)
        if is_tool:
            tool_event = cast(ToolCallReady, event)
            calls.append(tool_event.call)
    decoded_calls = []
    for call in calls:
        arguments = json.loads(call.arguments)
        decoded_calls.append((call.id, call.name, arguments))
    assert decoded_calls == [("a", "echo", {"text": "中文"}), ("b", "echo", {})]
    is_usage = isinstance(events[2], UsageReported)
    assert is_usage
    usage_event = cast(UsageReported, events[2])
    usage_value = usage_event.usage
    assert usage_value.total_tokens == 11
    assert usage_value.reasoning_tokens == 2
    expected_finish = ModelCompleted("tool_calls")
    assert events[-1] == expected_finish
    assert stream.closed


def invalid_payloads() -> list[bytes]:
    partial = delta({"content": "partial"})
    invalid_json = frame("not-json")
    no_finish = delta({})
    tool = {"index": 0, "function": {"name": "echo", "arguments": "{"}}
    broken_tool = delta({"tool_calls": [tool]}, "tool_calls")
    finish = delta({}, "stop")
    late = delta({"content": "late"})
    usage = frame({"choices": [], "usage": {"prompt_tokens": True}})
    done = frame("[DONE]")
    broken_tools = packet(broken_tool, done)
    late_content = packet(finish, late, done)
    invalid_usage = packet(finish, usage, done)
    truncated_frame = b'data: {"choices":[]}\n'
    invalid_utf8 = b"data: \xff\n\n"
    payloads = [partial, invalid_json, no_finish, broken_tools, late_content, invalid_usage]
    payloads.extend([truncated_frame, invalid_utf8])
    return payloads


INVALID_PAYLOADS = invalid_payloads()


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
async def test_invalid_or_truncated_stream_never_completes(payload: bytes) -> None:
    stream = ByteStream(payload)
    client = client_for(stream.respond)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        failure = pytest.raises(ModelUnavailableError)
        with failure:
            _ = await collect(gateway, request)
    assert stream.closed
    attempts = len(stream.requests)
    assert attempts == 1


@pytest.mark.parametrize("status", [429, 500, 503, 599])
async def test_transient_status_retries_before_output_only(status: int) -> None:
    attempts = 0
    content = delta({"content": "ok"}, "stop")
    done = frame("[DONE]")
    payload = packet(content, done)
    stream = ByteStream(payload)
    failed = ByteStream(b"failure")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = httpx.Response(status, stream=failed)
        else:
            response = stream.respond(request)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = await collect(gateway, request)
    assert attempts == 2
    expected = ModelCompleted("stop")
    assert events[-1] == expected
    assert failed.closed
    assert stream.closed


@pytest.mark.parametrize("failure_kind", ["connect", "read", "empty_delta"])
async def test_transport_failure_before_first_event_retries(failure_kind: str) -> None:
    attempts = 0
    empty = b""
    if failure_kind == "empty_delta":
        empty = delta({"role": "assistant"})
    failed = ByteStream(empty, failure=True)
    content = delta({"content": "ok"}, "stop")
    stream = ByteStream(content)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure_kind == "connect":
                raise httpx.ConnectTimeout("test-secret")
            response = failed.respond(request)
        else:
            response = stream.respond(request)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = await collect(gateway, request)
    assert attempts == 2
    expected = ModelCompleted("stop")
    assert events[-1] == expected
    if failure_kind != "connect":
        assert failed.closed


@pytest.mark.parametrize("kind", ["content", "reasoning", "usage"])
async def test_read_timeout_after_visible_output_never_retries(kind: str) -> None:
    if kind == "usage":
        payload = frame({"choices": [], "usage": {"prompt_tokens": 1}})
    else:
        key = "content" if kind == "content" else "reasoning"
        payload = delta({key: "partial"})
    stream = ByteStream(payload, failure=True)
    client = client_for(stream.respond)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = gateway.stream(request)
        first = await anext(events)
        assert first is not None
        failure = pytest.raises(ModelUnavailableError)
        with failure:
            _ = await anext(events)
    attempts = len(stream.requests)
    assert attempts == 1
    assert stream.closed


async def test_close_propagates_to_response_without_closing_shared_client() -> None:
    payload = delta({"content": "partial"})
    stream = ByteStream(payload)
    client = client_for(stream.respond)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = gateway.stream(request)
        _ = await anext(events)
        await events.aclose()
        assert not client.is_closed
        assert stream.closed


class BlockingStream(ByteStream):
    def __init__(self, payload: bytes) -> None:
        ByteStream.__init__(self, payload)
        self.waiting = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.payload
        waiting = self.waiting
        release = self.release
        waiting.set()
        await release.wait()


@pytest.mark.parametrize("has_output", [False, True])
async def test_cancellation_closes_response_without_retry(has_output: bool) -> None:
    payload = b""
    if has_output:
        payload = delta({"content": "partial"})
    stream = BlockingStream(payload)
    client = client_for(stream.respond)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = gateway.stream(request)
        if has_output:
            _ = await anext(events)
        pending = anext(events)
        task = asyncio.create_task(pending)
        signal = stream.waiting
        waiting = signal.wait()
        await asyncio.wait_for(waiting, timeout=2)
        task.cancel()
        failure = pytest.raises(asyncio.CancelledError)
        with failure:
            _ = await task
        assert not client.is_closed
    assert stream.closed
    attempts = len(stream.requests)
    assert attempts == 1


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_tools_unsupported_does_not_fall_back(status: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        body = {"error": {"param": "tools", "message": "test-secret"}}
        response = httpx.Response(status, json=body)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        failure = pytest.raises(ModelCapabilityError)
        with failure as captured:
            _ = await collect(gateway, request)
    assert attempts == 1
    message = str(captured.value)
    assert "test-secret" not in message
    assert "test-key" not in message


@pytest.mark.parametrize("status", [401, 403, 408, 409, 422, 503])
async def test_status_errors_are_sanitized_and_attempts_are_bounded(status: int) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        response = httpx.Response(status, json={"error": {"message": "test-secret"}})
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        failure = pytest.raises(ModelUnavailableError)
        with failure as captured:
            _ = await collect(gateway, request)
    expected_attempts = 2 if status == 503 else 1
    assert attempts == expected_attempts
    message = str(captured.value)
    assert "test-secret" not in message
    assert "test-key" not in message


async def test_connection_failures_respect_attempt_limit() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("test-secret")

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client, attempts=3)
        failure = pytest.raises(ModelUnavailableError)
        with failure as captured:
            _ = await collect(gateway, request)
    assert attempts == 3
    message = str(captured.value)
    assert "test-secret" not in message


@pytest.mark.parametrize("content_type", ["application/json", "text/plain"])
async def test_non_sse_response_is_rejected_and_closed(content_type: str) -> None:
    stream = ByteStream(b"test-secret")
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        response = httpx.Response(200, headers={"content-type": content_type}, stream=stream)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        failure = pytest.raises(ModelUnavailableError)
        with failure:
            _ = await collect(gateway, request)
    assert stream.closed
    assert attempts == 1


@pytest.mark.parametrize("include_usage", [False, True])
async def test_sdk_encodes_messages_tools_usage_and_preserves_timeout(include_usage: bool) -> None:
    payload = delta({}, "stop")
    stream = ByteStream(payload)
    client = client_for(stream.respond)
    options = ProviderOptions("https://test/custom/v1/", "test-key", include_usage)
    tool_call = ToolCall("a", "echo", '{"text":"中文"}')
    assistant = ModelMessage(MessageRole.ASSISTANT, "调用", (tool_call,))
    result = ModelMessage(MessageRole.TOOL, "结果", tool_call_id="a", name="echo")
    tool = ToolDefinition("echo", "测试", {"type": "object"})
    request = ModelRequest("test", (assistant, result), (tool,))
    async with client:
        gateway = OpenAICompatibleGateway(client, options)
        _ = await collect(gateway, request)
        assert not client.is_closed
    sent = stream.requests[0]
    assert sent.method == "POST"
    url = str(sent.url)
    assert url == "https://test/custom/v1/chat/completions"
    headers = sent.headers
    assert headers["authorization"] == "Bearer test-key"
    assert "x-stainless-package-version" in headers  # 官方 SDK，而非手写 POST。
    assert headers["accept"] == "text/event-stream"
    extensions = sent.extensions
    assert extensions["timeout"] == {"connect": 3, "read": 17, "write": 5, "pool": 7}
    body = json.loads(sent.content)
    assert body["model"] == "test"
    assert body["stream"] is True
    assert body["messages"] == [
        {"role": "assistant", "content": "调用", "tool_calls": [
            {"id": "a", "type": "function", "function": {
                "name": "echo", "arguments": '{"text":"中文"}',
            }},
        ]},
        {"role": "tool", "content": "结果", "tool_call_id": "a", "name": "echo"},
    ]
    assert body["tools"] == [{"type": "function", "function": {
        "name": "echo", "description": "测试", "parameters": {"type": "object"},
    }}]
    if include_usage:
        assert body["stream_options"] == {"include_usage": True}
    else:
        assert "stream_options" not in body


class OversizedErrorStream(ByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        chunk = b"x" * 16_384
        yield chunk
        raise AssertionError("错误正文超过上限后不应继续读取")


async def test_sdk_error_body_is_bounded_and_closed() -> None:
    stream = OversizedErrorStream(b"")

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(400, stream=stream)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        failure = pytest.raises(ModelUnavailableError)
        with failure:
            _ = await collect(gateway, request)
        assert not client.is_closed
    assert stream.closed


async def test_error_body_timeout_closes_response_and_retries() -> None:
    failed = ByteStream(b"partial", failure=True)
    payload = delta({}, "stop")
    succeeded = ByteStream(payload)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = httpx.Response(503, stream=failed)
        else:
            response = succeeded.respond(request)
        return response

    client = client_for(handler)
    request = request_with_tools()
    async with client:
        gateway = gateway_for(client)
        events = await collect(gateway, request)
    assert attempts == 2
    assert failed.closed
    expected = ModelCompleted("stop")
    assert events[-1] == expected


async def test_environment_proxies_are_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://invalid.example")
    payload = delta({}, "stop")
    stream = ByteStream(payload)
    client = client_for(stream.respond)
    request = ModelRequest("test", ())
    async with client:
        gateway = gateway_for(client)
        _ = await collect(gateway, request)
    attempts = len(stream.requests)
    assert attempts == 1
    sent = stream.requests[0]
    headers = sent.headers
    assert headers["authorization"] == "Bearer test-key"
    url = str(sent.url)
    assert url == "https://test/v1/chat/completions"
