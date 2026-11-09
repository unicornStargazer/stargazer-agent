"""运行输入和结果；与 HTTP、Profile 配置解析及会话提交解耦。"""

from dataclasses import dataclass

from dokkan_agent.domain.agent.models import ContentDelta, ReasoningDelta, UsageReported
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    ConversationTurn,
)


@dataclass(frozen=True, slots=True)
class RunProfile:
    """由后续对话应用解析的本轮模型；这里没有 Skill ID。"""

    id: str
    model: str
    system_prompt: str | None = None
    history_limit: int | None = None

    def __post_init__(self) -> None:
        if self.history_limit is not None and self.history_limit < 1:
            raise ValueError("history_limit 必须为正整数或省略")


@dataclass(frozen=True, slots=True)
class RunInput:
    command: ConversationCommand
    profile: RunProfile
    history: tuple[ConversationTurn, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    """运行成功仍未落库；ConversationService 提交后才能向 Web 发送 done。"""

    reply: AssistantReply
    model_calls: int
    tool_executions: int
    activated_skills: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunFinished:
    result: RunResult


type RunEvent = ContentDelta | ReasoningDelta | UsageReported | RunFinished


class ModelProtocolError(RuntimeError):
    """模型事件不完整或重复；禁止执行尚未完整结束的工具调用。"""


class ExplicitSkillError(ValueError):
    """用户显式选择了未知或无法激活的 Skill；不是可当文件路径处理的输入。"""
