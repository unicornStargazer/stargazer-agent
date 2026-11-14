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
        characters = len(content)
        if self.visible_characters + characters > self.maximum_characters:
            raise BudgetExceeded("本轮模型输出字符预算已耗尽。")
        self.visible_characters += characters
        target = self.reasoning if reasoning else self.contents
        target.append(content)

    def usage(self, current: TokenUsage | None = None) -> TokenUsage | None:
        snapshots = self.usages + ([current] if current is not None else [])
        has_usage = any(item is not None for item in snapshots)
        if not has_usage:
            return None
        totals: dict[str, int | None] = {}
        for name in ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
            known = []
            for item in snapshots:
                if item is not None:
                    value = getattr(item, name)
                    known.append(value)
            # 任一次调用缺失统计，则整轮该字段未知，不能展示不完整的部分和。
            total = None
            if known:
                fields_known = all(value is not None for value in known)
                if fields_known:
                    calls_known = all(item is not None for item in snapshots)
                    if calls_known:
                        total = sum(known)
            totals[name] = total
        try:
            usage = TokenUsage(**totals)
            return usage
        except ValueError:
            raise ModelProtocolError("模型用量汇总超出可表示范围。") from None

    def reply(self) -> AssistantReply:
        content = "".join(self.contents)
        visible = content.strip()
        if not visible:
            raise ModelProtocolError("模型未生成可见回答。")
        reasoning = "".join(self.reasoning)
        usage = self.usage()
        reply = AssistantReply(content, reasoning or None, usage)
        return reply
