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
from dokkan_agent.domain.agent.errors import ModelCapabilityError
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
        stream = self.stream(request, limits)
        closing = aclosing(stream)
        async with closing as events:
            async for event in events:
                match event:
                    case RunFinished():
                        return event.result
        raise ModelProtocolError("Agent 未完成运行。")

    async def stream(self, request: RunInput, limits: RunLimits | None = None) -> AsyncGenerator[RunEvent, None]:
        """每轮独立上下文；调用方关闭/取消事件流会关闭当前上游生成器。"""
        if not limits:
            limits = RunLimits()
        tools = self._tools
        definitions = tools.definitions()
        if definitions and not request.profile.supports_tools:
            raise ModelCapabilityError("所选模型未启用工具能力。")
        budget = RunBudget(limits)
        context = RunContext(budget)
        builder = self._builder
        messages = await builder.build(request, context)
        aggregate = RunAggregation(limits.max_context_characters)
        used_call_ids = {call.id for message in messages for call in message.tool_calls}
        model = self._model
        while True:
            builder.ensure_size(messages, context)
            budget.consume_model_call()
            state = ModelCallCollector(context, aggregate, used_call_ids)
            model_messages = tuple(messages)
            definitions = tools.definitions()
            model_request = ModelRequest(request.profile.model, model_messages, definitions)
            stream = model.stream(model_request)
            closing = aclosing(stream)
            async with closing as events:
                async for event in events:
                    forwarded = state.accept(event)
                    if forwarded is not None:
                        yield forwarded
            if not state.completed:
                raise ModelProtocolError("模型流未完整结束。")
            usages = aggregate.usages
            usages.append(state.usage)
            confirmed_usage = aggregate.usage()
            if state.usage is None and confirmed_usage is not None:
                # 后续调用缺少统计时撤回不完整合计，不能让页面继续显示前几次的部分和。
                usage_event = UsageReported(confirmed_usage)
                yield usage_event
            if not state.calls:
                reply = aggregate.reply()
                activated_skills = tuple(context.activated_skills)
                result = RunResult(reply, budget.model_calls, budget.tool_executions, activated_skills)
                finished_event = RunFinished(result)
                yield finished_event
                return
            contents = "".join(state.contents)
            calls = tuple(state.calls)
            assistant = ModelMessage(MessageRole.ASSISTANT, contents, tool_calls=calls)
            messages.append(assistant)
            for call in state.calls:
                tool_result = await tools.execute(call, context)
                message = tool_result_message(tool_result)
                messages.append(message)
