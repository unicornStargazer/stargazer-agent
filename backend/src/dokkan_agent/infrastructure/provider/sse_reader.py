"""有界 UTF-8 SSE 读取；字节边界可切开中文，协议分隔不能丢失。"""

import codecs
from collections.abc import AsyncIterator

import httpx

from dokkan_agent.domain.agent.errors import ModelUnavailableError

MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_CHARACTERS = 1024 * 1024


async def read_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """只产出 data 字段；接受 LF/CRLF、注释和多行 data，拒绝超限或残缺帧。"""
    decoder_type = codecs.getincrementaldecoder("utf-8")
    decoder = decoder_type("strict")
    buffer = ""
    lines: list[str] = []
    event_size = 0
    received = 0
    try:
        chunks = response.aiter_bytes()
        async for chunk in chunks:
            chunk_size = len(chunk)
            received += chunk_size
            if received > MAX_STREAM_BYTES:
                raise ModelUnavailableError("模型流超过大小限制。")
            decoded = decoder.decode(chunk)
            buffer += decoded
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.removesuffix("\r")
                line_size = len(line)
                event_size += line_size
                if event_size > MAX_EVENT_CHARACTERS:
                    raise ModelUnavailableError("模型事件超过大小限制。")
                if not line:
                    if lines:
                        data = "\n".join(lines)
                        yield data
                    lines = []
                    event_size = 0
                else:
                    is_data = line.startswith("data:")
                    if is_data:
                        value = line[5:]
                        value = value.removeprefix(" ")
                        lines.append(value)
            buffer_size = len(buffer)
            if buffer_size + event_size > MAX_EVENT_CHARACTERS:
                raise ModelUnavailableError("模型事件超过大小限制。")
        tail = decoder.decode(b"", final=True)
        buffer += tail
        remaining = buffer.strip()
        if remaining or lines:
            raise ModelUnavailableError("模型流存在未结束的事件。")
    except UnicodeError:
        raise ModelUnavailableError("模型流不是有效的 UTF-8。") from None
