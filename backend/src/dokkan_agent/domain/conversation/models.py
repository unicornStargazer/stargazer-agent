"""持久化以完整轮次为单位；临时工具消息不混入成功会话历史。"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from dokkan_agent.domain.agent.models import TokenUsage


@dataclass(frozen=True, slots=True)
class ConversationCommand:
    """经过接口校验的请求；profile_id 保留显式选择，None 不替换成默认 ID。"""

    session_id: str
    request_id: str
    message: str
    profile_id: str | None = None

    def fingerprint(self) -> str:
        """相同文本但不同显式模型也视为冲突；算法 v1 必须跨重启保持稳定。"""
        payload = {"version": 1, "message": self.message, "profileId": self.profile_id}
        canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        encoded = canonical.encode("utf-8")
        digest = hashlib.sha256(encoded)
        hexadecimal = digest.hexdigest()
        return "v1:" + hexadecimal


@dataclass(frozen=True, slots=True)
class AssistantReply:
    """成功回答：可见全文、Provider 公开推理及跨调用汇总用量。"""

    content: str
    reasoning: str | None = None
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """仓储提交单位；用户正文与助手回答同时写入，不允许半轮成功。"""

    user_content: str
    assistant: AssistantReply

    def __post_init__(self) -> None:
        raw_user_content = self.user_content
        user_content = raw_user_content.strip()
        if not user_content:
            raise ValueError("完整会话轮次的用户消息和助手回答不能为空")
        assistant_content = self.assistant.content
        stripped_content = assistant_content.strip()
        if not stripped_content:
            raise ValueError("完整会话轮次的用户消息和助手回答不能为空")


class RequestStatus(StrEnum):
    """请求执行状态；重启后的 running 收敛为 interrupted，不自动续跑副作用。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
