"""单 Agent 有界循环；只处理统一模型事件和工具结果，不硬编码领域 Skill 流程。"""

from collections.abc import AsyncGenerator
from contextlib import aclosing

from dokkan_agent.application.runtime.aggregation import RunAggregation
from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.runtime.context_builder import ContextBuilder, tool_result_message
from dokkan_agent.application.runtime.model_call import ModelCallCollector
from dokkan_agent.application.runtime.models import (
    ModelProtocolError,
    RunEvent,
    RunFinished,
    RunInput,
    RunResult,
)
from dokkan_agent.application.tool.registry import ToolRegistry
from dokkan_agent.domain.agent.budget import RunBudget, RunLimits
from dokkan_agent.domain.agent.models import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    UsageReported,
)
from dokkan_agent.domain.agent.ports import ModelGateway


class AgentRunner:
    def __init__(self, model: ModelGateway, tools: ToolRegistry, builder: ContextBuilder) -> None:
        self._model = model
        self._tools = tools
        self._builder = builder

    async def run(self, request: RunInput, limits: RunLimits | None = None) -> RunResult:
        """非流调用复用同一执行内核；成功返回结果但不落库。"""
        async with aclosing(self.stream(request, limits)) as events:
            async for event in events:
                if isinstance(event, RunFinished):
                    return event.result
        raise ModelProtocolError("Agent 未完成运行。")

    async def stream(
        self, request: RunInput, limits: RunLimits | None = None
    ) -> AsyncGenerator[RunEvent, None]:
        """每轮独立上下文；调用方关闭/取消事件流会关闭当前上游生成器。"""
        limits = limits or RunLimits()
        context = RunContext(RunBudget(limits))
        messages = await self._builder.build(request, context)
        aggregate = RunAggregation(limits.max_context_characters)
        used_call_ids = {call.id for message in messages for call in message.tool_calls}
        while True:
            self._builder.ensure_size(messages, context)
            context.budget.consume_model_call()
            state = ModelCallCollector(context, aggregate, used_call_ids)
            model_request = ModelRequest(
                request.profile.model, tuple(messages), self._tools.definitions()
            )
            async with aclosing(self._model.stream(model_request)) as events:
                async for event in events:
                    forwarded = state.accept(event)
                    if forwarded is not None:
                        yield forwarded
            if not state.completed:
                raise ModelProtocolError("模型流未完整结束。")
            aggregate.usages.append(state.usage)
            confirmed_usage = aggregate.usage()
            if state.usage is None and confirmed_usage is not None:
                # 后续调用缺少统计时撤回不完整合计，不能让页面继续显示前几次的部分和。
                yield UsageReported(confirmed_usage)
            if not state.calls:
                result = RunResult(
                    aggregate.reply(),
                    context.budget.model_calls,
                    context.budget.tool_executions,
                    tuple(context.activated_skills),
                )
                yield RunFinished(result)
                return
            messages.append(
                ModelMessage(
                    MessageRole.ASSISTANT, "".join(state.contents), tool_calls=tuple(state.calls)
                )
            )
            for call in state.calls:
                messages.append(tool_result_message(await self._tools.execute(call, context)))
