"""将 SDK 请求交给组合根连接池，并在 SDK 读取错误正文前限制大小。"""

import httpx

MAX_ERROR_BYTES = 16_384


class SharedClientTransport(httpx.AsyncBaseTransport):
    """不持有额外连接池、不读取代理环境，也不接管共享客户端的生命周期。"""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        client = self._client
        response = await client.send(request, stream=True)
        if 200 <= response.status_code < 300:
            return response
        # SDK 在抛出 APIStatusError 前会完整读取错误正文。预先有界读取，
        # 保留能力错误分类，并确保错误体超时、取消、截断时也关闭原始响应。
        body = bytearray()
        try:
            chunks = response.aiter_bytes()
            async for chunk in chunks:
                size = len(body)
                remaining = MAX_ERROR_BYTES - size
                body.extend(chunk[:remaining])
                size = len(body)
                if size >= MAX_ERROR_BYTES:
                    break
        finally:
            await response.aclose()
        content = bytes(body)
        bounded = httpx.Response(response.status_code, content=content, request=request)
        return bounded
