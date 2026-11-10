"""响应资源边界：断开连接关闭 Agent 流，状态清理不被 ASGI 的取消作用域打断。"""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable

import anyio
from fastapi import Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from dokkan_agent.application.conversation.service import PreparedConversation


class ConversationStreamingResponse(StreamingResponse):
    def __init__(
        self, content: AsyncGenerator[bytes, None], prepared: PreparedConversation
    ) -> None:
        super().__init__(
            content, media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )
        self._events = content
        self._prepared = prepared

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self._events.aclose()
                finally:
                    await self._prepared.aclose()


async def until_disconnect[T](
    request: Request,
    operation: Awaitable[T],
    abandon: Callable[[T], Awaitable[None]] | None = None,
) -> T:
    """非流请求也传播断开；请求体已消费后只监听 disconnect，不轮询占用事件循环。"""

    async def watch() -> None:
        while (await request.receive())["type"] != "http.disconnect":
            pass

    running = asyncio.ensure_future(operation)
    disconnected = asyncio.create_task(watch())
    delivered = False

    async def stop_tasks() -> None:
        disconnected.cancel()
        if not running.done():
            running.cancel()
        with anyio.CancelScope(shield=True):
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
            with anyio.CancelScope(shield=True):
                await stop_tasks()
                if abandon and not running.cancelled() and running.exception() is None:
                    # prepare 已完成但响应尚未接管租约时，也必须释放它。
                    await abandon(running.result())
