"""会话仓储边界：短事务保存完整轮次，不包裹模型或工具运行。"""

from dataclasses import dataclass
from typing import Protocol

from dokkan_agent.domain.agent.models import MessageRole
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    RequestStatus,
)


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    """旧库的单条原始消息；保留孤立历史，运行上下文另行配对。"""

    role: MessageRole
    content: str
    reply: AssistantReply | None = None


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """持久化请求摘要；response 是成功结果，attempt 是累计执行次数。"""

    fingerprint: str
    status: RequestStatus
    attempt: int
    profile_id: str
    response: AssistantReply | None = None


class ConversationRepository(Protocol):
    """方法失败抛 ConversationStorageError；取消传播，写操作自身保证原子性。"""

    async def recover_interrupted(self) -> int: ...

    async def get_profile(self, session_id: str) -> str | None: ...

    async def history(self, session_id: str) -> tuple[HistoryMessage, ...]: ...

    async def get_request(self, command: ConversationCommand) -> RequestRecord | None: ...

    async def begin_request(self, command: ConversationCommand, profile_id: str) -> None: ...

    async def commit_reply(self, command: ConversationCommand, reply: AssistantReply) -> None:
        """在同一事务保存两条消息、Profile 和可重放结果；不得部分成功。"""
        ...

    async def fail_request(
        self, command: ConversationCommand, status: RequestStatus, error_code: str
    ) -> None: ...

    async def delete(self, session_id: str) -> None: ...
