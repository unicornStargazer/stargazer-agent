"""兼容服务可能省略 DONE；只接受完整结束原因和干净传输结尾。"""

import httpx

from dokkan_agent.domain.agent.models import ModelCompleted, ModelRequest, UsageReported
from dokkan_agent.infrastructure.provider.openai_compatible import (
    OpenAICompatibleGateway,
    ProviderOptions,
)


async def test_clean_eof_after_finish_keeps_trailing_usage() -> None:
    content = (
        'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":1,"total_tokens":3}}\n\n'
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text=content
            )
        )
    ) as client:
        gateway = OpenAICompatibleGateway(client, ProviderOptions("https://test/v1", "test-key"))
        events = [event async for event in gateway.stream(ModelRequest("test", ()))]
    assert events[-1] == ModelCompleted("stop")
    assert isinstance(events[-2], UsageReported)
    assert events[-2].usage.total_tokens == 3
