"""单次模型流的完整性检查与收集；完整结束前绝不执行工具。"""

from dataclasses import dataclass, field

from dokkan_agent.application.runtime.aggregation import RunAggregation
from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.runtime.models import ModelProtocolError
from dokkan_agent.domain.agent.budget import BudgetExceeded
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    ModelCompleted,
    ModelEvent,
    ReasoningDelta,
    TokenUsage,
    ToolCallReady,
    UsageReported,
)
from dokkan_agent.domain.tool.models import ToolCall


@dataclass(slots=True)
class ModelCallCollector:
    """仅存本次调用临时值；共享本轮 ID 集合以防跨调用重复执行。"""

    context: RunContext
    aggregate: RunAggregation
    used_call_ids: set[str]
    contents: list[str] = field(default_factory=list, init=False)
    calls: list[ToolCall] = field(default_factory=list, init=False)
    usage: TokenUsage | None = field(default=None, init=False)
    completed: bool = field(default=False, init=False)

    def accept(self, event: ModelEvent) -> ContentDelta | ReasoningDelta | UsageReported | None:
        if self.completed:
            raise ModelProtocolError("模型在结束标记后继续发送事件。")
        aggregate = self.aggregate
        contents = self.contents
        match event:
            case ContentDelta(content):
                aggregate.append_text(content)
                contents.append(content)
                return event
            case ReasoningDelta(content):
                aggregate.append_text(content, reasoning=True)
                return event
            case UsageReported(usage):
                values = (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens, usage.total_tokens)
                has_usage = any(value is not None for value in values)
                if has_usage:
                    self.usage = usage
                    total = aggregate.usage(usage)
                    if not total:
                        total = TokenUsage()
                    reported = UsageReported(total)
                    return reported
            case ToolCallReady(call):
                self._collect_tool_call(call)
            case ModelCompleted(reason):
                expected = "tool_calls" if self.calls else "stop"
                if reason != expected:
                    raise ModelProtocolError("模型未正常结束或工具结束原因与结果不一致。")
                self.completed = True
            case _:
                raise ModelProtocolError("收到未知模型事件。")
        return None

    def _collect_tool_call(self, call: ToolCall) -> None:
        call_id = call.id
        identifier = call_id.strip()
        if not identifier:
            raise ModelProtocolError("模型工具调用 ID/名称缺失或 ID 重复。")
        name = call.name
        tool_name = name.strip()
        used_call_ids = self.used_call_ids
        if not tool_name or call.id in used_call_ids:
            raise ModelProtocolError("模型工具调用 ID/名称缺失或 ID 重复。")
        remaining = (
            self.context.budget.limits.max_tool_executions - self.context.budget.tool_executions
        )
        calls = self.calls
        count = len(calls)
        if count >= remaining:
            raise BudgetExceeded("模型请求的工具数超过本轮剩余预算。")
        used_call_ids.add(call.id)
        calls.append(call)
