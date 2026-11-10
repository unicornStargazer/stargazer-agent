"""单 worker 会话锁；仅存活跃会话，等待者取消后也会释放引用。"""

import asyncio
from dataclasses import dataclass, field

from dokkan_agent.domain.conversation.errors import SessionBusyError


@dataclass(slots=True)
class SessionEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    references: int = 0
    # 只向已经排队的重复请求传播失败；后续独立请求仍按持久化 attempt 有限重试。
    failures: dict[str, tuple[str, Exception]] = field(default_factory=dict)


@dataclass(slots=True)
class SessionLease:
    entry: SessionEntry
    waited: bool
    session_id: str


class SessionLocks:
    """所有字典操作都在同一事件循环且无 await；不宣称支持多进程。"""

    def __init__(self) -> None:
        self._entries: dict[str, SessionEntry] = {}

    async def acquire(self, session_id: str, *, reject_busy: bool = False) -> SessionLease:
        entry = self._entries.setdefault(session_id, SessionEntry())
        if reject_busy and entry.references:
            raise SessionBusyError("会话正在生成回复，暂时无法删除。")
        waited = bool(entry.references)
        entry.references += 1
        try:
            await entry.lock.acquire()
        except BaseException:
            self._drop_reference(session_id, entry)
            raise
        return SessionLease(entry, waited, session_id)

    def release(self, lease: SessionLease) -> None:
        lease.entry.lock.release()
        self._drop_reference(lease.session_id, lease.entry)

    def _drop_reference(self, session_id: str, entry: SessionEntry) -> None:
        entry.references -= 1
        if not entry.references:
            del self._entries[session_id]
