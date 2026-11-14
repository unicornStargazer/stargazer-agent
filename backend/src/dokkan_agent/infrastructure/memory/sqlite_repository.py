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
            connection_context = aiosqlite.connect(self._path, isolation_level=None, timeout=5)
            async with connection_context as connection:
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
        connection_context = self._connection(write=True)
        async with connection_context as connection:
            sql = (
                "UPDATE agent_requests SET status='interrupted', error_code='INTERRUPTED', "
                "updated_at_ms=? WHERE status='running'"
            )
            timestamp = _now_ms()
            cursor = await connection.execute(sql, (timestamp,))
            return cursor.rowcount

    async def get_profile(self, session_id: str) -> str | None:
        connection_context = self._connection()
        async with connection_context as connection:
            cursor_context = connection.execute("SELECT profile_id FROM conversation_sessions WHERE session_id=?", (session_id,))
            async with cursor_context as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def history(self, session_id: str) -> tuple[HistoryMessage, ...]:
        connection_context = self._connection()
        async with connection_context as connection:
            sql = (
                "SELECT role, content, reasoning, usage_json FROM conversation_messages "
                "WHERE session_id=? ORDER BY sequence"
            )
            cursor_context = connection.execute(sql, (session_id,))
            async with cursor_context as cursor:
                rows = await cursor.fetchall()
        messages: list[HistoryMessage] = []
        for row in rows:
            role = MessageRole(row["role"])
            reply = None
            if role == MessageRole.ASSISTANT:
                usage = decode_usage(row["usage_json"])
                reply = AssistantReply(row["content"], row["reasoning"], usage)
            message = HistoryMessage(role, row["content"], reply)
            messages.append(message)
        history = tuple(messages)
        return history

    async def get_request(self, command: ConversationCommand) -> RequestRecord | None:
        connection_context = self._connection()
        async with connection_context as connection:
            record = await self._read_request(connection, command)
            return record

    async def _read_request(self, connection: aiosqlite.Connection, command: ConversationCommand) -> RequestRecord | None:
        sql = (
            "SELECT request_fingerprint, status, attempt, profile_id, response_json "
            "FROM agent_requests WHERE session_id=? AND request_id=?"
        )
        cursor_context = connection.execute(sql, (command.session_id, command.request_id))
        async with cursor_context as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        fingerprint = command.fingerprint()
        if row["request_fingerprint"] != fingerprint:
            raise RequestConflictError("请求 ID 已用于其他输入。")
        status = RequestStatus(row["status"])
        reply = None
        if row["response_json"]:
            reply = decode_reply(row["response_json"])
        record = RequestRecord(row["request_fingerprint"], status, row["attempt"], row["profile_id"], reply)
        return record

    async def begin_request(self, command: ConversationCommand, profile_id: str) -> None:
        connection_context = self._connection(write=True)
        async with connection_context as connection:
            existing = await self._read_request(connection, command)
            if existing and existing.status in {RequestStatus.RUNNING, RequestStatus.SUCCEEDED}:
                raise RequestConflictError("请求不能重复进入运行状态。")
            if existing and existing.attempt >= MAX_REQUEST_ATTEMPTS:
                raise RequestAttemptsExceeded("同一请求最多尝试三次。")
            timestamp = _now_ms()
            sql = (
                "INSERT INTO conversation_sessions(session_id, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?) ON CONFLICT(session_id) DO NOTHING"
            )
            await connection.execute(sql, (command.session_id, timestamp, timestamp))
            sql = (
                "INSERT INTO agent_requests(session_id, request_id, request_fingerprint, status, "
                "attempt, profile_id, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, 'running', 1, ?, ?, ?) "
                "ON CONFLICT(session_id, request_id) DO UPDATE SET status='running', "
                "attempt=agent_requests.attempt+1, profile_id=excluded.profile_id, "
                "response_json=NULL, error_code=NULL, updated_at_ms=excluded.updated_at_ms"
            )
            fingerprint = command.fingerprint()
            parameters = (command.session_id, command.request_id, fingerprint, profile_id, timestamp, timestamp)
            await connection.execute(sql, parameters)

    async def commit_reply(self, command: ConversationCommand, reply: AssistantReply) -> None:
        connection_context = self._connection(write=True)
        async with connection_context as connection:
            record = await self._read_request(connection, command)
            if record is None or record.status != RequestStatus.RUNNING:
                raise ConversationStorageError("请求不在可提交状态。")
            sql = (
                "SELECT COALESCE(MAX(sequence), -1)+1 FROM conversation_messages "
                "WHERE session_id=?"
            )
            cursor_context = connection.execute(sql, (command.session_id,))
            async with cursor_context as cursor:
                row = await cursor.fetchone()
            assert row is not None
            sequence = row[0]
            timestamp = _now_ms()
            usage = None
            if reply.usage is not None:
                payload = usage_payload(reply.usage)
                usage = json.dumps(payload)
            sql = (
                "INSERT INTO conversation_messages(session_id, sequence, role, content, reasoning, "
                "usage_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)"
            )
            messages = [
                (command.session_id, sequence, "user", command.message, None, None, timestamp),
                (command.session_id, sequence + 1, "assistant", reply.content, reply.reasoning, usage, timestamp),
            ]
            await connection.executemany(sql, messages)
            await connection.execute("UPDATE conversation_sessions SET profile_id=?, updated_at_ms=? WHERE session_id=?", (record.profile_id, timestamp, command.session_id))
            sql = (
                "UPDATE agent_requests SET status='succeeded', response_json=?, error_code=NULL, "
                "updated_at_ms=? WHERE session_id=? AND request_id=? AND status='running'"
            )
            response = encode_reply(reply)
            parameters = (response, timestamp, command.session_id, command.request_id)
            await connection.execute(sql, parameters)

    async def fail_request(self, command: ConversationCommand, status: RequestStatus, error_code: str) -> None:
        if status not in {RequestStatus.FAILED, RequestStatus.INTERRUPTED}:
            raise ValueError("失败状态无效")
        connection_context = self._connection(write=True)
        async with connection_context as connection:
            sql = (
                "UPDATE agent_requests SET status=?, error_code=?, updated_at_ms=? "
                "WHERE session_id=? AND request_id=? AND request_fingerprint=? "
                "AND status='running'"
            )
            timestamp = _now_ms()
            fingerprint = command.fingerprint()
            parameters = (status.value, error_code, timestamp, command.session_id, command.request_id, fingerprint)
            await connection.execute(sql, parameters)

    async def delete(self, session_id: str) -> None:
        connection_context = self._connection(write=True)
        async with connection_context as connection:
            await connection.execute("DELETE FROM conversation_sessions WHERE session_id=?", (session_id,))


def _now_ms() -> int:
    timestamp_ns = time.time_ns()
    return timestamp_ns // 1_000_000
