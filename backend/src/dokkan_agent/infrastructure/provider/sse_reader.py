"""有界 UTF-8 SSE 读取；字节边界可切开中文，协议分隔不能丢失。"""

import codecs
from collections.abc import AsyncIterator

import httpx

from dokkan_agent.domain.agent.errors import ModelUnavailableError

MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_CHARACTERS = 1024 * 1024


async def read_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """只产出 data 字段；接受 LF/CRLF、注释和多行 data，拒绝超限或残缺帧。"""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    lines: list[str] = []
    event_size = 0
    received = 0
    try:
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > MAX_STREAM_BYTES:
                raise ModelUnavailableError("模型流超过大小限制。")
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.removesuffix("\r")
                event_size += len(line)
                if event_size > MAX_EVENT_CHARACTERS:
                    raise ModelUnavailableError("模型事件超过大小限制。")
                if not line:
                    if lines:
                        yield "\n".join(lines)
                    lines = []
                    event_size = 0
                elif line.startswith("data:"):
                    lines.append(line[5:].removeprefix(" "))
            if len(buffer) + event_size > MAX_EVENT_CHARACTERS:
                raise ModelUnavailableError("模型事件超过大小限制。")
        buffer += decoder.decode(b"", final=True)
        if buffer.strip() or lines:
            raise ModelUnavailableError("模型流存在未结束的事件。")
    except UnicodeError:
        raise ModelUnavailableError("模型流不是有效的 UTF-8。") from None
