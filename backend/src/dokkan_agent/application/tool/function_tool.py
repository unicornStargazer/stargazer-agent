"""用有类型的参数和输出模型包装异步函数，统一 Schema 与服务端校验。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.domain.agent.budget import BudgetExceeded
from dokkan_agent.domain.skill.errors import SkillAccessError
from dokkan_agent.domain.tool.models import JsonValue, ToolDefinition


class ToolParameters(BaseModel):
    """工具参数拒绝额外字段和自动类型转换，不依赖模型遵守 Schema。"""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class ToolOutputError(RuntimeError):
    """处理器违反输出契约；不能误报成用户参数无效，也不暴露处理器异常。"""


class ExecutableTool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, arguments: dict[str, JsonValue], context: RunContext) -> JsonValue: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class FunctionTool[Parameters: BaseModel, Output: BaseModel]:
    """函数工具适配器；参数错误和输出错误分开，上层注册器统一转为安全结果。"""

    name: str
    description: str
    parameters: type[Parameters]
    output: type[Output]
    handler: Callable[[Parameters, RunContext], Awaitable[Output]]

    @property
    def definition(self) -> ToolDefinition:
        schema = cast(dict[str, JsonValue], self.parameters.model_json_schema())
        return ToolDefinition(self.name, self.description, schema)

    async def execute(self, arguments: dict[str, JsonValue], context: RunContext) -> JsonValue:
        parsed = self.parameters.model_validate(arguments, strict=True)
        try:
            response = await self.handler(parsed, context)
            # 先转回字段映射再校验，避免 model_construct 或实例默认跳过重校验。
            fields = (
                response.model_dump(warnings="error")
                if isinstance(response, BaseModel)
                else response
            )
            checked = self.output.model_validate(fields, strict=True)
            return cast(JsonValue, checked.model_dump(mode="json", exclude_none=True))
        except (BudgetExceeded, SkillAccessError):
            raise
        except Exception:
            raise ToolOutputError("工具输出不符合声明契约。") from None
