"""HTTPX OpenAI 兼容流适配；连接池由组合根持有，不尝试第二条非流降级路径。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import httpx

from dokkan_agent.domain.agent.errors import ModelCapabilityError, ModelUnavailableError
from dokkan_agent.domain.agent.models import ModelEvent, ModelRequest
from dokkan_agent.infrastructure.provider.request_encoder import encode_request
from dokkan_agent.infrastructure.provider.sse_reader import read_sse_data
from dokkan_agent.infrastructure.provider.stream_decoder import CompletionDecoder


@dataclass(frozen=True, slots=True)
class ProviderOptions:
    """只接受连接参数；密钥不进入 repr，客户端超时由组合根显式设置。"""

    base_url: str
    api_key: str = field(repr=False)
    include_stream_usage: bool = True
    max_attempts: int = 2


class OpenAICompatibleGateway:
    def __init__(self, client: httpx.AsyncClient, options: ProviderOptions) -> None:
        self._client = client
        self._options = options

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        """仅首个领域事件之前重试临时网络/429/5xx；输出后失败必须原样结束运行。"""
        emitted = False
        for attempt in range(self._options.max_attempts):
            try:
                async with self._client.stream(
                    "POST",
                    self._options.base_url.rstrip("/") + "/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._options.api_key}",
                        "Accept": "text/event-stream",
                    },
                    json=encode_request(request, self._options.include_stream_usage),
                ) as response:
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        if not emitted and attempt + 1 < self._options.max_attempts:
                            await asyncio.sleep(0.2 * (attempt + 1))
                            continue
                    if response.status_code != 200:
                        await _raise_upstream_error(response, bool(request.tools))
                    if (
                        response.headers.get("content-type", "").split(";")[0].lower()
                        != "text/event-stream"
                    ):
                        raise ModelUnavailableError("模型没有返回 SSE。")
                    decoder = CompletionDecoder()
                    async for data in read_sse_data(response):
                        for event in decoder.accept(data):
                            emitted = True
                            yield event
                        if decoder.done:
                            return
                    for event in decoder.complete_at_eof():
                        emitted = True
                        yield event
                    return
            except httpx.TransportError:
                if emitted or attempt + 1 >= self._options.max_attempts:
                    raise ModelUnavailableError("模型连接失败或超时。") from None
                await asyncio.sleep(0.2 * (attempt + 1))
        raise ModelUnavailableError("模型暂时不可用。")


async def _raise_upstream_error(response: httpx.Response, tools_requested: bool) -> None:
    """仅检查有界结构化能力错误，不向客户端透传上游正文或字符串异常。"""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk[: 16_384 - len(body)])
        if len(body) >= 16_384:
            break
    if tools_requested and response.status_code in {400, 404, 422}:
        try:
            error = json.loads(body).get("error", {})
            if isinstance(error, dict) and (
                error.get("param") in {"tools", "tool_choice", "tool_calls", "functions"}
                or error.get("code") in {"unsupported_tools", "tool_use_not_supported"}
            ):
                raise ModelCapabilityError("模型不支持所需的工具能力。")
        except (ValueError, TypeError, AttributeError, RecursionError):
            pass
    raise ModelUnavailableError("模型上游请求失败。")
