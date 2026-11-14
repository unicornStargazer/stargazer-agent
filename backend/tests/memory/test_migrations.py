"""在临时脱敏旧库上验证兼容性、原子回滚、版本防护与新请求表约束。"""
import sqlite3
from pathlib import Path

import pytest

from dokkan_agent.infrastructure.memory.migration import MigrationError, migrate_database


def build_legacy_database(path: Path, with_metadata: bool) -> None:
    """构造两代 TS 表结构；文字、顺序号、时间和 JSON 格式都必须原样保留。"""
    database_connection = sqlite3.connect(path)
    with database_connection as connection:
        connection.execute('CREATE TABLE conversation_sessions (\n            session_id TEXT PRIMARY KEY NOT NULL,\n            created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL\n        )')
        connection.execute("CREATE TABLE conversation_messages (\n            session_id TEXT NOT NULL, sequence INTEGER NOT NULL,\n            role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,\n            created_at_ms INTEGER NOT NULL, PRIMARY KEY(session_id, sequence),\n            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE\n        )")
        connection.execute("INSERT INTO conversation_sessions VALUES ('legacy', 1000, 2000)")
        connection.executemany('INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)', [('legacy', 7, 'user', '  用户原始正文\n', 1000), ('legacy', 8, 'assistant', '旧回答 😀', 2000)])
        if with_metadata:
            connection.execute('ALTER TABLE conversation_sessions ADD COLUMN profile_id TEXT')
            connection.execute('ALTER TABLE conversation_messages ADD COLUMN reasoning TEXT')
            connection.execute('ALTER TABLE conversation_messages ADD COLUMN usage_json TEXT')
            connection.execute('UPDATE conversation_sessions SET profile_id = ? WHERE session_id = ?', ('previous-model', 'legacy'))
            connection.execute('UPDATE conversation_messages SET reasoning = ?, usage_json = ? WHERE session_id = ? AND sequence = ?', ('已有公开推理\n', '{ "inputTokens": 2, "totalTokens": 5 }', 'legacy', 8))


@pytest.mark.parametrize('with_metadata', [False, True])
async def test_migrations_preserve_legacy_records_and_are_idempotent(tmp_path: Path, with_metadata: bool) -> None:
    database = tmp_path / 'legacy.sqlite'
    build_legacy_database(database, with_metadata)
    applied_migrations = await migrate_database(database)
    assert applied_migrations == (1, 2)
    applied_migrations_2 = await migrate_database(database)
    assert applied_migrations_2 == ()
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        cursor = connection.execute('SELECT session_id, created_at_ms, updated_at_ms, profile_id FROM conversation_sessions')
        session = cursor.fetchone()
        cursor_2 = connection.execute('SELECT sequence, role, content, created_at_ms, reasoning, usage_json FROM conversation_messages ORDER BY sequence')
        messages = cursor_2.fetchall()
        assert session == ('legacy', 1000, 2000, 'previous-model' if with_metadata else None)
        assert messages[0] == (7, 'user', '  用户原始正文\n', 1000, None, None)
        assert messages[1] == (8, 'assistant', '旧回答 😀', 2000, '已有公开推理\n' if with_metadata else None, '{ "inputTokens": 2, "totalTokens": 5 }' if with_metadata else None)


async def test_failed_migration_rolls_back_columns_and_ledger(tmp_path: Path) -> None:
    database = tmp_path / 'broken.sqlite'
    build_legacy_database(database, with_metadata=False)
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        # 故意模拟外部同名但不兼容的表，使 002 建索引失败。
        connection.execute('CREATE TABLE agent_requests (unrelated TEXT)')
    expected_error = pytest.raises(MigrationError, match='已回滚')
    with expected_error:
        await migrate_database(database)
    database_connection_2 = sqlite3.connect(database)
    with database_connection_2 as connection:
        cursor = connection.execute('PRAGMA table_info(conversation_messages)')
        columns = {row[1] for row in cursor}
        assert 'reasoning' not in columns
        cursor_2 = connection.execute("SELECT name FROM sqlite_master WHERE name = 'agent_schema_migrations'")
        fetchone = cursor_2.fetchone()
        assert fetchone is None
        cursor_3 = connection.execute('SELECT content FROM conversation_messages ORDER BY sequence')
        fetchall = cursor_3.fetchall()
        assert fetchall == [('  用户原始正文\n',), ('旧回答 😀',)]


async def test_future_version_is_rejected_without_rewriting_data(tmp_path: Path) -> None:
    database = tmp_path / 'future.sqlite'
    await migrate_database(database)
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        connection.execute('INSERT INTO agent_schema_migrations VALUES (99, 0)')
    expected_error = pytest.raises(MigrationError, match='拒绝修改')
    with expected_error:
        await migrate_database(database)
    database_connection_2 = sqlite3.connect(database)
    with database_connection_2 as connection:
        cursor = connection.execute('SELECT version FROM agent_schema_migrations ORDER BY version')
        fetchall = cursor.fetchall()
        assert fetchall == [(1,), (2,), (99,)]


async def test_request_constraints_and_session_cascade(tmp_path: Path) -> None:
    database = tmp_path / 'new.sqlite'
    await migrate_database(database)
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute("INSERT INTO conversation_sessions VALUES ('s1', NULL, 1, 1)")
        insert = 'INSERT INTO agent_requests (\n            session_id, request_id, request_fingerprint, status, attempt, profile_id,\n            response_json, error_code, created_at_ms, updated_at_ms\n        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        running = ('s1', 'r1', 'v1:hash', 'running', 1, 'default', None, None, 1, 1)
        connection.execute(insert, running)
        expected_error = pytest.raises(sqlite3.IntegrityError)
        with expected_error:
            connection.execute(insert, running)
        expected_error_2 = pytest.raises(sqlite3.IntegrityError)
        with expected_error_2:
            connection.execute(insert, ('s1', 'r2', 'v1:hash', 'succeeded', 1, 'default', None, None, 1, 1))
        expected_error_3 = pytest.raises(sqlite3.IntegrityError)
        with expected_error_3:
            connection.execute(insert, ('missing', 'r3', 'v1:hash', 'running', 1, 'default', None, None, 1, 1))
        connection.execute('DELETE FROM conversation_sessions WHERE session_id = ?', ('s1',))
        cursor = connection.execute('SELECT request_id FROM agent_requests WHERE session_id = ?', ('s1',))
        fetchall = cursor.fetchall()
        assert fetchall == []


async def test_legacy_orphan_messages_roll_back_entire_migration(tmp_path: Path) -> None:
    database = tmp_path / 'orphan.sqlite'
    build_legacy_database(database, with_metadata=False)
    database_connection = sqlite3.connect(database)
    with database_connection as connection:
        connection.execute('INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)', ('missing-session', 1, 'user', '测试孤立消息', 1000))
    expected_error = pytest.raises(MigrationError, match='失效的会话关联')
    with expected_error:
        await migrate_database(database)
    database_connection_2 = sqlite3.connect(database)
    with database_connection_2 as connection:
        cursor = connection.execute("SELECT name FROM sqlite_master WHERE name = 'agent_requests'")
        fetchone = cursor.fetchone()
        assert fetchone is None
