"""统一流协议，避免启用 Tool 后丢失正文、公开推理文本或用量。"""

from dataclasses import dataclass
from enum import StrEnum

from dokkan_agent.domain.tool.models import ToolCall, ToolDefinition


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Provider 提供的用量；None 表示未知，reasoning_tokens 通常是输出子项。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.input_tokens,
            self.output_tokens,
            self.reasoning_tokens,
            self.total_tokens,
        ):
            if value is not None and (
                type(value) is not int or not 0 <= value <= 9_007_199_254_740_991
            ):
                raise ValueError("Token 用量必须是非负安全整数或未知")


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """单次模型输入；工具交互只在本轮存在，不直接作为长期会话记录。"""

    role: MessageRole
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """单次模型调用快照；Skill 由上下文构造器装入消息，不由模型配置选择。"""

    model: str
    messages: tuple[ModelMessage, ...]
    tools: tuple[ToolDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class ContentDelta:
    """本次增量可见文字；运行器将所有调用的已展示文字按顺序汇总。"""

    content: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    """仅包含 Provider 已公开的推理文字，不能要求或编造隐藏思维链。"""

    content: str


@dataclass(frozen=True, slots=True)
class UsageReported:
    """本次调用的累计统计；同一次调用取最后有效值，跨调用再求和。"""

    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class ToolCallReady:
    """完整工具名和参数已归并；增量片段不能作为该事件提前发出。"""

    call: ToolCall


@dataclass(frozen=True, slots=True)
class ModelCompleted:
    """结束单次模型调用，并非整轮提交成功；HTTP done 由应用提交后生成。"""

    finish_reason: str


type ModelEvent = ContentDelta | ReasoningDelta | UsageReported | ToolCallReady | ModelCompleted
