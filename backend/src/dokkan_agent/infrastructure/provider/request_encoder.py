"""将统一消息转成供应商请求，工具结果继续使用标准 tool_call_id 关联。"""

from typing import Any

from dokkan_agent.domain.agent.models import ModelMessage, ModelRequest


def encode_request(request: ModelRequest, include_usage: bool) -> dict[str, Any]:
    messages = []
    for message in request.messages:
        encoded = _encode_message(message)
        messages.append(encoded)
    payload: dict[str, Any] = {
        "model": request.model,
        "stream": True,
        "messages": messages,
    }
    if include_usage:
        payload["stream_options"] = {"include_usage": True}
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in request.tools
        ]
    return payload


def _encode_message(message: ModelMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.arguments,
                },
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.name is not None:
        payload["name"] = message.name
    return payload
