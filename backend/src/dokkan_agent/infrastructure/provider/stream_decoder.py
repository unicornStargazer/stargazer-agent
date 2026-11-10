"""Chat Completions 增量解码；finish_reason 之后仍接收 usage，最终才完成调用。"""

import json
from dataclasses import dataclass
from typing import Any

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
            return self._accept(data)
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
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError
        events: list[ModelEvent] = []
        if choices:
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                raise ValueError
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise ValueError
            if self._finish_reason is not None:
                # 一些服务的 usage 尾帧仍带空 delta；非空正文或工具则是协议错误。
                if any(
                    delta.get(key)
                    for key in ("content", "reasoning_content", "reasoning", "tool_calls")
                ):
                    raise ValueError
                if choice.get("finish_reason") is not None:
                    raise ValueError
            events.extend(self._read_delta(delta))
            finish = choice.get("finish_reason")
            if finish is not None:
                if not isinstance(finish, str) or not finish:
                    raise ValueError
                self._finish_reason = finish
        usage = payload.get("usage")
        if usage is not None:
            events.append(UsageReported(_read_usage(usage)))
        return events

    def _read_delta(self, delta: dict[str, Any]) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        for key, event_type in (("content", ContentDelta),):
            value = delta.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError
                if value:
                    events.append(event_type(value))
        reasoning = delta.get("reasoning_content")
        if reasoning is None:
            reasoning = delta.get("reasoning")
        if reasoning is not None:
            if not isinstance(reasoning, str):
                raise ValueError
            if reasoning:
                events.append(ReasoningDelta(reasoning))
        calls = delta.get("tool_calls")
        if calls is not None:
            if not isinstance(calls, list) or len(calls) > MAX_TOOL_CALLS:
                raise ValueError
            for call in calls:
                self._append_tool(call)
        if delta.get("function_call"):
            raise ValueError("不混用旧版 function_call 协议")
        return events

    def _append_tool(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError
        index = payload.get("index")
        if type(index) is not int or not 0 <= index < MAX_TOOL_CALLS:
            raise ValueError
        fragment = self._tools.setdefault(index, ToolFragments())
        if payload.get("type", "function") != "function":
            raise ValueError
        identifier = payload.get("id")
        if identifier is not None:
            if not isinstance(identifier, str):
                raise ValueError
            fragment.identifier += identifier
        function = payload.get("function", {})
        if not isinstance(function, dict):
            raise ValueError
        for key in ("name", "arguments"):
            value = function.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError
            setattr(fragment, key, getattr(fragment, key) + value)
        if (
            len(fragment.identifier) > 256
            or len(fragment.name) > 128
            or len(fragment.arguments) > MAX_ARGUMENT_CHARACTERS
        ):
            raise ValueError

    def _finish(self) -> list[ModelEvent]:
        if self._finish_reason is None:
            raise ValueError("缺少结束原因")
        if bool(self._tools) != (self._finish_reason == "tool_calls"):
            raise ValueError("工具与结束原因不匹配")
        events: list[ModelEvent] = []
        identifiers: set[str] = set()
        if sorted(self._tools) != list(range(len(self._tools))):
            raise ValueError("工具索引不连续")
        for index in sorted(self._tools):
            fragment = self._tools[index]
            if not fragment.identifier.strip() or not fragment.name.strip():
                raise ValueError("工具缺少标识或名称")
            if fragment.identifier in identifiers:
                raise ValueError("工具标识重复")
            arguments = json.loads(fragment.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            identifiers.add(fragment.identifier)
            events.append(
                ToolCallReady(ToolCall(fragment.identifier, fragment.name, fragment.arguments))
            )
        events.append(ModelCompleted(self._finish_reason))
        return events


def _read_usage(payload: object) -> TokenUsage:
    if not isinstance(payload, dict):
        raise ValueError
    details = payload.get("completion_tokens_details") or {}
    if not isinstance(details, dict):
        raise ValueError
    counts = [
        payload.get("prompt_tokens"),
        payload.get("completion_tokens"),
        details.get("reasoning_tokens"),
        payload.get("total_tokens"),
    ]
    if any(
        value is not None and (type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER)
        for value in counts
    ):
        raise ValueError
    return TokenUsage(*counts)
