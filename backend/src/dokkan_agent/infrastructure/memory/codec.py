"""SQLite JSON 编解码；沿用旧消息元数据和完整响应形状，不依赖 HTTP DTO。"""

import json

from dokkan_agent.domain.agent.models import TokenUsage
from dokkan_agent.domain.conversation.errors import ConversationStorageError
from dokkan_agent.domain.conversation.models import AssistantReply

USAGE_FIELDS = {
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
    "reasoningTokens": "reasoning_tokens",
    "totalTokens": "total_tokens",
}
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def usage_payload(usage: TokenUsage) -> dict[str, int]:
    """不将未知字段伪造为零，也不重复累加 reasoning 子项。"""
    payload: dict[str, int] = {}
    fields = USAGE_FIELDS.items()
    for external, internal in fields:
        count = getattr(usage, internal)
        if count is not None:
            payload[external] = count
    return payload


def decode_usage(content: str | None) -> TokenUsage | None:
    if content is None:
        return None
    try:
        payload = json.loads(content)
        is_mapping = isinstance(payload, dict)
        if not is_mapping:
            raise ValueError
        for key in payload:
            if key not in USAGE_FIELDS:
                raise ValueError
        values = payload.values()
        for value in values:
            value_type = type(value)
            if value_type is not int or not 0 <= value <= MAX_SAFE_INTEGER:
                raise ValueError
        items = payload.items()
        fields = {USAGE_FIELDS[key]: value for key, value in items}
        usage = TokenUsage(**fields)
        return usage
    except (ValueError, TypeError, RecursionError):
        raise ConversationStorageError("会话用量数据无效。") from None


def encode_reply(reply: AssistantReply) -> str:
    message: dict[str, object] = {"role": "assistant", "content": reply.content}
    if reply.reasoning is not None:
        message["reasoning"] = reply.reasoning
    if reply.usage is not None:
        usage = usage_payload(reply.usage)
        message["usage"] = usage
    content = json.dumps({"message": message}, ensure_ascii=True, separators=(",", ":"))
    return content


def decode_reply(content: str) -> AssistantReply:
    try:
        payload = json.loads(content)
        message = payload["message"]
        if message["role"] != "assistant":
            raise ValueError
        is_content_text = isinstance(message["content"], str)
        if not is_content_text:
            raise ValueError
        reasoning = message.get("reasoning")
        if reasoning is not None:
            is_reasoning_text = isinstance(reasoning, str)
            if not is_reasoning_text:
                raise ValueError
        usage = None
        if "usage" in message:
            usage_json = json.dumps(message["usage"])
            usage = decode_usage(usage_json)
        reply = AssistantReply(message["content"], reasoning, usage)
        return reply
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ConversationStorageError("请求重放数据无效。") from None
