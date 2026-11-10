"""适配旧 SQLite 会话表；连接按操作关闭，网络执行期间不持有写事务。"""

import json
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from dokkan_agent.domain.agent.models import MessageRole
from dokkan_agent.domain.conversation.errors import (
    ConversationStorageError,
    RequestAttemptsExceeded,
    RequestConflictError,
)
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    RequestStatus,
)
from dokkan_agent.domain.conversation.ports import HistoryMessage, RequestRecord
from dokkan_agent.infrastructure.memory.codec import (
    decode_reply,
    decode_usage,
    encode_reply,
    usage_payload,
)

MAX_REQUEST_ATTEMPTS = 3


class SqliteConversationRepository:
    """单 worker 的持久化适配；每次写入仍用事务和状态条件防止误覆盖。"""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path

    @asynccontextmanager
    async def _connection(self, *, write: bool = False) -> AsyncIterator[aiosqlite.Connection]:
        try:
            async with aiosqlite.connect(self._path, isolation_level=None, timeout=5) as connection:
                connection.row_factory = aiosqlite.Row
                await connection.execute("PRAGMA foreign_keys = ON")
                if write:
                    await connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    if write:
                        await connection.commit()
                except BaseException:
                    if write:
                        await connection.rollback()
                    raise
        except sqlite3.Error:
            raise ConversationStorageError("会话存储暂时不可用。") from None

    async def recover_interrupted(self) -> int:
        """仅服务启动时调用；不恢复网络操作，不自动重跑请求。"""
        async with self._connection(write=True) as connection:
            cursor = await connection.execute(
                "UPDATE agent_requests SET status='interrupted', error_code='INTERRUPTED', "
                "updated_at_ms=? WHERE status='running'",
                (_now_ms(),),
            )
            return cursor.rowcount

    async def get_profile(self, session_id: str) -> str | None:
        async with self._connection() as connection:
            async with connection.execute(
                "SELECT profile_id FROM conversation_sessions WHERE session_id=?", (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def history(self, session_id: str) -> tuple[HistoryMessage, ...]:
        async with self._connection() as connection:
            async with connection.execute(
                "SELECT role, content, reasoning, usage_json FROM conversation_messages "
                "WHERE session_id=? ORDER BY sequence",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        messages: list[HistoryMessage] = []
        for row in rows:
            role = MessageRole(row["role"])
            reply = (
                AssistantReply(row["content"], row["reasoning"], decode_usage(row["usage_json"]))
                if role == MessageRole.ASSISTANT
                else None
            )
            messages.append(HistoryMessage(role, row["content"], reply))
        return tuple(messages)

    async def get_request(self, command: ConversationCommand) -> RequestRecord | None:
        async with self._connection() as connection:
            return await self._read_request(connection, command)

    async def _read_request(
        self, connection: aiosqlite.Connection, command: ConversationCommand
    ) -> RequestRecord | None:
        async with connection.execute(
            "SELECT request_fingerprint, status, attempt, profile_id, response_json "
            "FROM agent_requests WHERE session_id=? AND request_id=?",
            (command.session_id, command.request_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != command.fingerprint():
            raise RequestConflictError("请求 ID 已用于其他输入。")
        return RequestRecord(
            row["request_fingerprint"],
            RequestStatus(row["status"]),
            row["attempt"],
            row["profile_id"],
            decode_reply(row["response_json"]) if row["response_json"] else None,
        )

    async def begin_request(self, command: ConversationCommand, profile_id: str) -> None:
        async with self._connection(write=True) as connection:
            existing = await self._read_request(connection, command)
            if existing and existing.status in {RequestStatus.RUNNING, RequestStatus.SUCCEEDED}:
                raise RequestConflictError("请求不能重复进入运行状态。")
            if existing and existing.attempt >= MAX_REQUEST_ATTEMPTS:
                raise RequestAttemptsExceeded("同一请求最多尝试三次。")
            timestamp = _now_ms()
            await connection.execute(
                "INSERT INTO conversation_sessions(session_id, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?) ON CONFLICT(session_id) DO NOTHING",
                (command.session_id, timestamp, timestamp),
            )
            await connection.execute(
                "INSERT INTO agent_requests(session_id, request_id, request_fingerprint, status, "
                "attempt, profile_id, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, 'running', 1, ?, ?, ?) "
                "ON CONFLICT(session_id, request_id) DO UPDATE SET status='running', "
                "attempt=agent_requests.attempt+1, profile_id=excluded.profile_id, "
                "response_json=NULL, error_code=NULL, updated_at_ms=excluded.updated_at_ms",
                (
                    command.session_id,
                    command.request_id,
                    command.fingerprint(),
                    profile_id,
                    timestamp,
                    timestamp,
                ),
            )

    async def commit_reply(self, command: ConversationCommand, reply: AssistantReply) -> None:
        async with self._connection(write=True) as connection:
            record = await self._read_request(connection, command)
            if record is None or record.status != RequestStatus.RUNNING:
                raise ConversationStorageError("请求不在可提交状态。")
            async with connection.execute(
                "SELECT COALESCE(MAX(sequence), -1)+1 FROM conversation_messages "
                "WHERE session_id=?",
                (command.session_id,),
            ) as cursor:
                row = await cursor.fetchone()
            assert row is not None
            sequence = row[0]
            timestamp = _now_ms()
            usage = json.dumps(usage_payload(reply.usage)) if reply.usage is not None else None
            await connection.executemany(
                "INSERT INTO conversation_messages(session_id, sequence, role, content, reasoning, "
                "usage_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (command.session_id, sequence, "user", command.message, None, None, timestamp),
                    (
                        command.session_id,
                        sequence + 1,
                        "assistant",
                        reply.content,
                        reply.reasoning,
                        usage,
                        timestamp,
                    ),
                ],
            )
            await connection.execute(
                "UPDATE conversation_sessions SET profile_id=?, updated_at_ms=? WHERE session_id=?",
                (record.profile_id, timestamp, command.session_id),
            )
            await connection.execute(
                "UPDATE agent_requests SET status='succeeded', response_json=?, error_code=NULL, "
                "updated_at_ms=? WHERE session_id=? AND request_id=? AND status='running'",
                (encode_reply(reply), timestamp, command.session_id, command.request_id),
            )

    async def fail_request(
        self, command: ConversationCommand, status: RequestStatus, error_code: str
    ) -> None:
        if status not in {RequestStatus.FAILED, RequestStatus.INTERRUPTED}:
            raise ValueError("失败状态无效")
        async with self._connection(write=True) as connection:
            await connection.execute(
                "UPDATE agent_requests SET status=?, error_code=?, updated_at_ms=? "
                "WHERE session_id=? AND request_id=? AND request_fingerprint=? "
                "AND status='running'",
                (
                    status.value,
                    error_code,
                    _now_ms(),
                    command.session_id,
                    command.request_id,
                    command.fingerprint(),
                ),
            )

    async def delete(self, session_id: str) -> None:
        async with self._connection(write=True) as connection:
            await connection.execute(
                "DELETE FROM conversation_sessions WHERE session_id=?", (session_id,)
            )


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
