"""工具契约保留调用 ID；参数只有收集完整后才允许交给执行层校验。"""

from dataclasses import dataclass
from enum import StrEnum

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """一次完整调用；arguments 是尚未做 Schema 校验的完整 JSON 文本。"""

    id: str
    name: str
    arguments: str


class ToolErrorCode(StrEnum):
    """可反馈给模型的稳定错误类别；不包含底层异常和敏感文件路径。"""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNKNOWN_SKILL = "UNKNOWN_SKILL"
    SKILL_NOT_ACTIVE = "SKILL_NOT_ACTIVE"
    SKILL_CHANGED = "SKILL_CHANGED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_PATH_INVALID = "RESOURCE_PATH_INVALID"
    RESOURCE_TOO_LARGE = "RESOURCE_TOO_LARGE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


@dataclass(frozen=True, slots=True)
class ToolFailure:
    """安全失败描述；message 面向模型，不得直接填入 IO/Provider 异常原文。"""

    code: ToolErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """执行结果与原始调用精确对应；payload 与 error 必须且只能出现一种。"""

    call_id: str
    name: str
    payload: JsonValue = None
    error: ToolFailure | None = None

    def __post_init__(self) -> None:
        raw_call_id = self.call_id
        call_id = raw_call_id.strip()
        if not call_id:
            raise ValueError("工具调用 ID 和名称不能为空")
        raw_name = self.name
        name = raw_name.strip()
        if not name:
            raise ValueError("工具调用 ID 和名称不能为空")
        if (self.payload is None) == (self.error is None):
            raise ValueError("工具结果必须提供非 null payload 或 error，且不能同时提供")

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """可向模型公开的注册工具定义；Schema 不代表执行权限。"""

    name: str
    description: str
    parameters: dict[str, JsonValue]
