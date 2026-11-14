"""Chat Completions 增量解码；finish_reason 之后仍接收 usage，最终才完成调用。"""

import json
from dataclasses import dataclass
from typing import Any, cast

from dokkan_agent.domain.agent.errors import ModelUnavailableError
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

MAX_TOOL_CALLS = 128
MAX_ARGUMENT_CHARACTERS = 64_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991


@dataclass(slots=True)
class ToolFragments:
    identifier: str = ""
    name: str = ""
    arguments: str = ""


class CompletionDecoder:
    """一份状态仅用于一次 HTTP 调用；任何残缺工具都不会产生可执行事件。"""

    def __init__(self) -> None:
        self._tools: dict[int, ToolFragments] = {}
        self._finish_reason: str | None = None
        self.done = False

    def accept(self, data: str) -> list[ModelEvent]:
        try:
            events = self._accept(data)
            return events
        except (ValueError, TypeError, KeyError, RecursionError):
            raise ModelUnavailableError("模型返回了无效的流式数据。") from None

    def complete_at_eof(self) -> list[ModelEvent]:
        """兼容省略 [DONE] 的服务：仅正常 EOF 且已有有效 finish_reason 才能完成。"""
        try:
            if self.done:
                raise ValueError
            events = self._finish()
            self.done = True
            return events
        except (ValueError, TypeError, KeyError, RecursionError):
            raise ModelUnavailableError("模型流提前结束或工具调用不完整。") from None

    def _accept(self, data: str) -> list[ModelEvent]:
        if self.done:
            raise ValueError("结束后不能再有事件")
        if data == "[DONE]":
            completed_events = self._finish()
            self.done = True
            return completed_events
        payload = json.loads(data)
        is_mapping = isinstance(payload, dict)
        if not is_mapping or "error" in payload:
            raise ValueError
        choices = payload.get("choices")
        is_list = isinstance(choices, list)
        if not is_list:
            raise ValueError
        choice_count = len(choices)
        if choice_count > 1:
            raise ValueError
        events: list[ModelEvent] = []
        if choices:
            choice = choices[0]
            is_mapping = isinstance(choice, dict)
            if not is_mapping:
                raise ValueError
            index = choice.get("index", 0)
            if index != 0:
                raise ValueError
            delta = choice.get("delta", {})
            is_mapping = isinstance(delta, dict)
            if not is_mapping:
                raise ValueError
            if self._finish_reason is not None:
                # 一些服务的 usage 尾帧仍带空 delta；非空正文或工具是协议错误。
                for key in ("content", "reasoning_content", "reasoning", "tool_calls"):
                    value = delta.get(key)
                    if value:
                        raise ValueError
                finish = choice.get("finish_reason")
                if finish is not None:
                    raise ValueError
            deltas = self._read_delta(delta)
            events.extend(deltas)
            finish = choice.get("finish_reason")
            if finish is not None:
                is_text = isinstance(finish, str)
                if not is_text or not finish:
                    raise ValueError
                self._finish_reason = finish
        usage = payload.get("usage")
        if usage is not None:
            counts = _read_usage(usage)
            usage_event = UsageReported(counts)
            events.append(usage_event)
        return events

    def _read_delta(self, delta: dict[str, Any]) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        value = delta.get("content")
        if value is not None:
            is_text = isinstance(value, str)
            if not is_text:
                raise ValueError
            if value:
                content = ContentDelta(value)
                events.append(content)
        reasoning = delta.get("reasoning_content")
        if reasoning is None:
            reasoning = delta.get("reasoning")
        if reasoning is not None:
            is_text = isinstance(reasoning, str)
            if not is_text:
                raise ValueError
            if reasoning:
                reasoning_event = ReasoningDelta(reasoning)
                events.append(reasoning_event)
        calls = delta.get("tool_calls")
        if calls is not None:
            is_list = isinstance(calls, list)
            if not is_list:
                raise ValueError
            call_count = len(calls)
            if call_count > MAX_TOOL_CALLS:
                raise ValueError
            for call in calls:
                self._append_tool(call)
        legacy_call = delta.get("function_call")
        if legacy_call:
            raise ValueError("不混用旧版 function_call 协议")
        return events

    def _append_tool(self, payload: object) -> None:
        is_mapping = isinstance(payload, dict)
        if not is_mapping:
            raise ValueError
        payload = cast(dict[str, Any], payload)
        index = payload.get("index")
        index_type = type(index)
        if index_type is not int:
            raise ValueError
        index = cast(int, index)
        if not 0 <= index < MAX_TOOL_CALLS:
            raise ValueError
        tools = self._tools
        initial = ToolFragments()
        fragment = tools.setdefault(index, initial)
        call_type = payload.get("type", "function")
        if call_type != "function":
            raise ValueError
        identifier = payload.get("id")
        if identifier is not None:
            is_text = isinstance(identifier, str)
            if not is_text:
                raise ValueError
            fragment.identifier += identifier
        function = payload.get("function", {})
        is_mapping = isinstance(function, dict)
        if not is_mapping:
            raise ValueError
        for key in ("name", "arguments"):
            value = function.get(key)
            if value is None:
                continue
            is_text = isinstance(value, str)
            if not is_text:
                raise ValueError
            previous = getattr(fragment, key)
            setattr(fragment, key, previous + value)
        id_size = len(fragment.identifier)
        name_size = len(fragment.name)
        argument_size = len(fragment.arguments)
        if id_size > 256 or name_size > 128 or argument_size > MAX_ARGUMENT_CHARACTERS:
            raise ValueError

    def _finish(self) -> list[ModelEvent]:
        if self._finish_reason is None:
            raise ValueError("缺少结束原因")
        has_tools = bool(self._tools)
        if has_tools != (self._finish_reason == "tool_calls"):
            raise ValueError("工具与结束原因不匹配")
        events: list[ModelEvent] = []
        identifiers: set[str] = set()
        indices = sorted(self._tools)
        count = len(self._tools)
        expected_range = range(count)
        expected = list(expected_range)
        if indices != expected:
            raise ValueError("工具索引不连续")
        for index in indices:
            fragment = self._tools[index]
            identifier = fragment.identifier
            name = fragment.name
            clean_id = identifier.strip()
            clean_name = name.strip()
            if not clean_id or not clean_name:
                raise ValueError("工具缺少标识或名称")
            if identifier in identifiers:
                raise ValueError("工具标识重复")
            arguments = json.loads(fragment.arguments)
            is_mapping = isinstance(arguments, dict)
            if not is_mapping:
                raise ValueError("工具参数必须是 JSON 对象")
            identifiers.add(identifier)
            call = ToolCall(identifier, name, fragment.arguments)
            tool_event = ToolCallReady(call)
            events.append(tool_event)
        completed = ModelCompleted(self._finish_reason)
        events.append(completed)
        return events


def _read_usage(payload: object) -> TokenUsage:
    is_mapping = isinstance(payload, dict)
    if not is_mapping:
        raise ValueError
    payload = cast(dict[str, Any], payload)
    details = payload.get("completion_tokens_details")
    if not details:
        details = {}
    is_mapping = isinstance(details, dict)
    if not is_mapping:
        raise ValueError
    input_tokens = payload.get("prompt_tokens")
    output_tokens = payload.get("completion_tokens")
    reasoning_tokens = details.get("reasoning_tokens")
    total_tokens = payload.get("total_tokens")
    counts = [input_tokens, output_tokens, reasoning_tokens, total_tokens]
    for value in counts:
        value_type = type(value)
        if value is not None and (value_type is not int or not 0 <= value <= MAX_SAFE_INTEGER):
            raise ValueError
    usage = TokenUsage(*counts)
    return usage
