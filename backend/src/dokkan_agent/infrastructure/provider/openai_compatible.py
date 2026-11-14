"""官方 OpenAI SDK 请求适配；保留有界 SSE 校验和领域事件协议。"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from openai import APIConnectionError, APIError, APIStatusError, AsyncOpenAI

from dokkan_agent.domain.agent.errors import ModelCapabilityError, ModelUnavailableError
from dokkan_agent.domain.agent.models import ModelEvent, ModelRequest
from dokkan_agent.infrastructure.provider.request_encoder import encode_request
from dokkan_agent.infrastructure.provider.sdk_transport import SharedClientTransport
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
        # 无连接池包装客户端将 SDK 请求交给组合根；显式 timeout 和 trust_env
        # 避免 SDK 默认值覆盖配置或读取环境代理。共享连接池仍由组合根关闭。
        transport = SharedClientTransport(client)
        sdk_client = httpx.AsyncClient(transport=transport, timeout=client.timeout, trust_env=False, follow_redirects=False)
        self._sdk = AsyncOpenAI(api_key=options.api_key, base_url=options.base_url, http_client=sdk_client, timeout=client.timeout, max_retries=0, default_headers={"Accept": "text/event-stream"})
        self._options = options
        chat = self._sdk.chat
        completions = chat.completions
        self._streaming = completions.with_streaming_response

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        """仅首个领域事件之前重试临时网络/429/5xx；不做非流式降级。"""
        emitted = False
        attempts = range(self._options.max_attempts)
        for attempt in attempts:
            try:
                payload = encode_request(request, self._options.include_stream_usage)
                streaming = self._streaming
                manager = streaming.create(**payload)
                async with manager as sdk_response:
                    response = sdk_response.http_response
                    _validate_response(response)
                    decoder = CompletionDecoder()
                    # SDK 的默认 SSE 解码允许残缺帧和无界事件。使用公开原始响应
                    # API 保留严格 UTF-8、大小限制、DONE/干净 EOF 和工具完整性校验。
                    data_stream = read_sse_data(response)
                    async for data in data_stream:
                        events = decoder.accept(data)
                        for event in events:
                            emitted = True
                            yield event
                        if decoder.done:
                            return
                    events = decoder.complete_at_eof()
                    for event in events:
                        emitted = True
                        yield event
                    return
            except APIStatusError as error:
                status = error.status_code
                transient = status == 429 or 500 <= status < 600
                if not transient or emitted or attempt + 1 >= self._options.max_attempts:
                    tools_requested = bool(request.tools)
                    _raise_upstream_error(error, tools_requested)
            except (APIConnectionError, httpx.TransportError):
                if emitted or attempt + 1 >= self._options.max_attempts:
                    raise ModelUnavailableError("模型连接失败或超时。") from None
            except APIError:
                raise ModelUnavailableError("模型上游请求失败。") from None
            await asyncio.sleep(0.2 * (attempt + 1))
        raise ModelUnavailableError("模型暂时不可用。")


def _validate_response(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise ModelUnavailableError("模型上游请求失败。")
    headers = response.headers
    content_type = headers.get("content-type", "")
    parts = content_type.split(";")
    media_type = parts[0].lower()
    if media_type != "text/event-stream":
        raise ModelUnavailableError("模型没有返回 SSE。")


def _raise_upstream_error(error: APIStatusError, tools_requested: bool) -> None:
    """只识别结构化能力错误，不透传 SDK 异常中的密钥、正文或请求信息。"""
    payload = error.body
    if tools_requested and error.status_code in {400, 404, 422}:
        is_mapping = isinstance(payload, dict)
        if is_mapping:
            # SDK 的 body 通常已解包 error；同时兼容其他兼容服务的外层结构。
            mapping = cast(dict[str, Any], payload)
            payload = mapping.get("error", payload)
            is_mapping = isinstance(payload, dict)
        if is_mapping:
            mapping = cast(dict[str, Any], payload)
            parameter = mapping.get("param")
            code = mapping.get("code")
            if parameter in ("tools", "tool_choice", "tool_calls", "functions") or code in ("unsupported_tools", "tool_use_not_supported"):
                raise ModelCapabilityError("模型不支持所需的工具能力。") from None
    raise ModelUnavailableError("模型上游请求失败。") from None
