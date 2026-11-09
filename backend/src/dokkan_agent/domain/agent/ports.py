"""模型边界只传领域对象；供应商协议、HTTP 资源和重试策略留在适配器。"""

from collections.abc import AsyncGenerator
from typing import Protocol

from dokkan_agent.domain.agent.models import ModelEvent, ModelRequest


class ModelGateway(Protocol):
    """一次调用产生有序事件；失败抛依赖异常，取消必须传播到上游连接。"""

    def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        """仅在完整归并后发 ToolCallReady；成功结束时发一次 ModelCompleted。"""
        ...
