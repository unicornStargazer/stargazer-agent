"""单条用户消息的有界运行规则；不依赖配置框架、工具实现或持久化。"""

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """达到硬上限时终止整轮，不能当普通工具错误反复消耗模型请求。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RunLimits:
    """计数以本轮为作用域；字符使用 Unicode 码点，不伪装成 Token 统计。"""

    max_model_calls: int = 12
    max_tool_executions: int = 24
    max_activated_skills: int = 4
    max_resource_reads: int = 8
    max_resource_characters: int = 16_000
    max_disclosure_characters: int = 64_000
    max_context_characters: int = 128_000

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            value_type = type(value)
            if value_type is not int or value < 1:
                raise ValueError("运行预算必须是正整数")


@dataclass(slots=True)
class RunBudget:
    """可变计数只能由所属 RunContext 持有，不跨请求共享。"""

    limits: RunLimits
    model_calls: int = 0
    tool_executions: int = 0
    activated_skills: int = 0
    resource_reads: int = 0
    disclosure_characters: int = 0

    def consume_model_call(self) -> None:
        self._require_available(self.model_calls, self.limits.max_model_calls, "模型调用次数")
        self.model_calls += 1

    def consume_tool_execution(self) -> None:
        self._require_available(self.tool_executions, self.limits.max_tool_executions, "工具执行次数")
        self.tool_executions += 1

    def consume_activation(self) -> None:
        self._require_available(self.activated_skills, self.limits.max_activated_skills, "Skill 激活数")
        self.activated_skills += 1

    def consume_resource_read(self) -> None:
        self._require_available(self.resource_reads, self.limits.max_resource_reads, "资源读取次数")
        self.resource_reads += 1

    def consume_disclosure(self, characters: int) -> None:
        total = self.disclosure_characters + characters
        if total > self.limits.max_disclosure_characters:
            raise BudgetExceeded("本轮工具与指令披露字符预算已耗尽。")
        self.disclosure_characters = total

    @staticmethod
    def _require_available(current: int, maximum: int, label: str) -> None:
        if current >= maximum:
            raise BudgetExceeded(f"本轮{label}预算已耗尽。")
