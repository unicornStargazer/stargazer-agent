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
    return {
        external: count
        for external, internal in USAGE_FIELDS.items()
        if (count := getattr(usage, internal)) is not None
    }


def decode_usage(content: str | None) -> TokenUsage | None:
    if content is None:
        return None
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or any(key not in USAGE_FIELDS for key in payload):
            raise ValueError
        if any(
            type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER
            for value in payload.values()
        ):
            raise ValueError
        return TokenUsage(**{USAGE_FIELDS[key]: value for key, value in payload.items()})
    except (ValueError, TypeError, RecursionError):
        raise ConversationStorageError("会话用量数据无效。") from None


def encode_reply(reply: AssistantReply) -> str:
    message: dict[str, object] = {"role": "assistant", "content": reply.content}
    if reply.reasoning is not None:
        message["reasoning"] = reply.reasoning
    if reply.usage is not None:
        message["usage"] = usage_payload(reply.usage)
    return json.dumps({"message": message}, ensure_ascii=True, separators=(",", ":"))


def decode_reply(content: str) -> AssistantReply:
    try:
        payload = json.loads(content)
        message = payload["message"]
        if message["role"] != "assistant" or not isinstance(message["content"], str):
            raise ValueError
        reasoning = message.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            raise ValueError
        usage = decode_usage(json.dumps(message["usage"])) if "usage" in message else None
        return AssistantReply(message["content"], reasoning, usage)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ConversationStorageError("请求重放数据无效。") from None
