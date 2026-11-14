"""工具执行唯一入口；参数、输出、预算和错误都在此收敛，不执行未注册名称。"""

import json
import math
from collections.abc import Sequence
from typing import cast

from pydantic import ValidationError

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.tool.function_tool import ExecutableTool
from dokkan_agent.domain.agent.budget import BudgetExceeded
from dokkan_agent.domain.skill.errors import SkillAccessError
from dokkan_agent.domain.tool.models import (
    JsonValue,
    ToolCall,
    ToolDefinition,
    ToolErrorCode,
    ToolFailure,
    ToolResult,
)

MAX_ARGUMENT_CHARACTERS = 32_000


def serialize_tool_result(result: ToolResult) -> str:
    """安全 JSON 信封保留成功/失败语义；正文作为数据，不拼成系统消息。"""
    payload: dict[str, JsonValue] = {"success": result.success}
    if result.error:
        payload["error"] = {"code": result.error.code.value, "message": result.error.message}
    else:
        payload["result"] = result.payload
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return encoded


class ToolRegistry:
    def __init__(self, tools: Sequence[ExecutableTool]) -> None:
        self._tools = {tool.definition.name: tool for tool in tools}
        registered_count = len(self._tools)
        provided_count = len(tools)
        if registered_count != provided_count:
            raise ValueError("工具名称不能重复注册")

    def definitions(self) -> tuple[ToolDefinition, ...]:
        tools = self._tools
        registered = tools.values()
        definitions = tuple(tool.definition for tool in registered)
        return definitions

    async def execute(self, call: ToolCall, context: RunContext) -> ToolResult:
        """所有调用都消耗次数；可恢复失败交给模型纠正，预算耗尽则直接终止。"""
        budget = context.budget
        budget.consume_tool_execution()
        result = await self._execute_registered(call, context)
        try:
            encoded = serialize_tool_result(result)
        except (ValueError, TypeError, RecursionError):
            result = self._failure(call, ToolErrorCode.EXECUTION_FAILED, "工具输出格式无效。")
            encoded = serialize_tool_result(result)
        # 显式激活也经此入口，统一按实际披露的完整 JSON 计费，避免漏算或重复计费。
        characters = len(encoded)
        budget.consume_disclosure(characters)
        return result

    async def _execute_registered(self, call: ToolCall, context: RunContext) -> ToolResult:
        tools = self._tools
        tool = tools.get(call.name)
        if tool is None:
            result = self._failure(call, ToolErrorCode.UNKNOWN_TOOL, "工具未注册。")
            return result
        try:
            arguments = _parse_arguments(call.arguments)
            output = await tool.execute(arguments, context)
            result = ToolResult(call.id, call.name, payload=output)
            return result
        except (ValidationError, ValueError, RecursionError):
            result = self._failure(call, ToolErrorCode.INVALID_ARGUMENTS, "工具参数不符合声明格式。")
            return result
        except SkillAccessError as error:
            message = str(error)
            result = self._failure(call, error.code, message)
            return result
        except BudgetExceeded:
            raise
        except Exception:
            result = self._failure(call, ToolErrorCode.EXECUTION_FAILED, "工具执行失败，请检查服务端实现。")
            return result

    @staticmethod
    def _failure(call: ToolCall, code: ToolErrorCode, message: str) -> ToolResult:
        failure = ToolFailure(code, message)
        result = ToolResult(call.id, call.name, error=failure)
        return result


def _parse_arguments(raw: str) -> dict[str, JsonValue]:
    characters = len(raw)
    if characters > MAX_ARGUMENT_CHARACTERS:
        raise ValueError("工具参数过长")
    payload: object = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant, parse_float=_parse_finite_float)
    is_object = isinstance(payload, dict)
    if not is_object:
        raise ValueError("工具参数必须为 JSON 对象")
    arguments = cast(dict[str, JsonValue], payload)
    return arguments


def _unique_pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 参数不能包含重复键")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("JSON 参数不能包含非有限数值")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    finite = math.isfinite(number)
    if not finite:
        raise ValueError("JSON 参数不能包含溢出数值")
    return number
