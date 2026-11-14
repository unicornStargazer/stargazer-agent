"""响应资源边界：断开连接关闭 Agent 流，状态清理不被 ASGI 的取消作用域打断。"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

import anyio
from fastapi import Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from dokkan_agent.application.conversation.service import PreparedConversation


class ConversationStreamingResponse(StreamingResponse):
    def __init__(self, content: AsyncGenerator[bytes, None], prepared: PreparedConversation) -> None:
        StreamingResponse.__init__(self, content, media_type="text/event-stream", headers={"Cache-Control": "no-store"})
        self._events = content
        self._prepared = prepared

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await StreamingResponse.__call__(self, scope, receive, send)
        finally:
            cleanup_scope = anyio.CancelScope(shield=True)
            with cleanup_scope:
                try:
                    events = self._events
                    await events.aclose()
                finally:
                    prepared = self._prepared
                    await prepared.aclose()


async def until_disconnect[T](request: Request, operation: Awaitable[T], abandon: Callable[[T], Awaitable[None]] | None = None) -> T:
    """非流请求也传播断开；请求体已消费后只监听 disconnect，不轮询占用事件循环。"""

    async def watch() -> None:
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                break

    running = asyncio.ensure_future(operation)
    watcher = watch()
    disconnected = asyncio.create_task(watcher)
    delivered = False

    async def stop_tasks() -> None:
        disconnected.cancel()
        finished = running.done()
        if not finished:
            running.cancel()
        cleanup_scope = anyio.CancelScope(shield=True)
        with cleanup_scope:
            await asyncio.gather(running, disconnected, return_exceptions=True)

    try:
        done, _ = await asyncio.wait({running, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        if running not in done:
            raise asyncio.CancelledError
        result = await running
        await stop_tasks()
        delivered = True
        return result
    finally:
        if not delivered:
            cleanup_scope = anyio.CancelScope(shield=True)
            with cleanup_scope:
                await stop_tasks()
                if abandon:
                    cancelled = running.cancelled()
                    if not cancelled:
                        error = running.exception()
                        if error is None:
                            # prepare 已完成但响应尚未接管租约时，也必须释放它。
                            abandoned = running.result()
                            await abandon(abandoned)
