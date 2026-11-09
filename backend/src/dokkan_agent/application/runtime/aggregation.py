"""聚合一轮所有模型调用的展示结果；同次 usage 用最后值，跨调用才累加。"""

from dataclasses import dataclass, field

from dokkan_agent.application.runtime.models import ModelProtocolError
from dokkan_agent.domain.agent.budget import BudgetExceeded
from dokkan_agent.domain.agent.models import TokenUsage
from dokkan_agent.domain.conversation.models import AssistantReply


@dataclass(slots=True)
class RunAggregation:
    """只累计已向调用方发出的可见文字，不丢掉工具调用前的中间说明。"""

    maximum_characters: int
    contents: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    usages: list[TokenUsage | None] = field(default_factory=list)
    visible_characters: int = 0

    def append_text(self, content: str, *, reasoning: bool = False) -> None:
        if self.visible_characters + len(content) > self.maximum_characters:
            raise BudgetExceeded("本轮模型输出字符预算已耗尽。")
        self.visible_characters += len(content)
        (self.reasoning if reasoning else self.contents).append(content)

    def usage(self, current: TokenUsage | None = None) -> TokenUsage | None:
        snapshots = self.usages + ([current] if current is not None else [])
        if not any(item is not None for item in snapshots):
            return None
        totals: dict[str, int | None] = {}
        for name in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
            known = [getattr(item, name) for item in snapshots if item is not None]
            # 任一次调用缺失统计，则整轮该字段未知，不能展示不完整的部分和。
            totals[name] = (
                sum(known)
                if known
                and all(value is not None for value in known)
                and all(item is not None for item in snapshots)
                else None
            )
        return TokenUsage(**totals)

    def reply(self) -> AssistantReply:
        content = "".join(self.contents)
        if not content.strip():
            raise ModelProtocolError("模型未生成可见回答。")
        return AssistantReply(content, "".join(self.reasoning) or None, self.usage())
