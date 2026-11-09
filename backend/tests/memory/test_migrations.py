"""在临时脱敏旧库上验证兼容性、原子回滚、版本防护与新请求表约束。"""

import sqlite3
from pathlib import Path

import pytest

from dokkan_agent.infrastructure.memory.migration import MigrationError, migrate_database


def build_legacy_database(path: Path, with_metadata: bool) -> None:
    """构造两代 TS 表结构；文字、顺序号、时间和 JSON 格式都必须原样保留。"""
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE conversation_sessions (
            session_id TEXT PRIMARY KEY NOT NULL,
            created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
        )""")
        connection.execute("""CREATE TABLE conversation_messages (
            session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL, PRIMARY KEY(session_id, sequence),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        )""")
        connection.execute("INSERT INTO conversation_sessions VALUES ('legacy', 1000, 2000)")
        connection.executemany(
            "INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)",
            [
                ("legacy", 7, "user", "  用户原始正文\n", 1000),
                ("legacy", 8, "assistant", "旧回答 😀", 2000),
            ],
        )
        if with_metadata:
            connection.execute("ALTER TABLE conversation_sessions ADD COLUMN profile_id TEXT")
            connection.execute("ALTER TABLE conversation_messages ADD COLUMN reasoning TEXT")
            connection.execute("ALTER TABLE conversation_messages ADD COLUMN usage_json TEXT")
            connection.execute(
                "UPDATE conversation_sessions SET profile_id = ? WHERE session_id = ?",
                ("previous-model", "legacy"),
            )
            connection.execute(
                "UPDATE conversation_messages SET reasoning = ?, usage_json = ? "
                "WHERE session_id = ? AND sequence = ?",
                ("已有公开推理\n", '{ "inputTokens": 2, "totalTokens": 5 }', "legacy", 8),
            )


@pytest.mark.parametrize("with_metadata", [False, True])
async def test_migrations_preserve_legacy_records_and_are_idempotent(
    tmp_path: Path, with_metadata: bool
) -> None:
    database = tmp_path / "legacy.sqlite"
    build_legacy_database(database, with_metadata)
    assert await migrate_database(database) == (1, 2)
    assert await migrate_database(database) == ()
    with sqlite3.connect(database) as connection:
        session = connection.execute(
            "SELECT session_id, created_at_ms, updated_at_ms, profile_id FROM conversation_sessions"
        ).fetchone()
        messages = connection.execute(
            "SELECT sequence, role, content, created_at_ms, reasoning, usage_json "
            "FROM conversation_messages ORDER BY sequence"
        ).fetchall()
        assert session == ("legacy", 1000, 2000, "previous-model" if with_metadata else None)
        assert messages[0] == (7, "user", "  用户原始正文\n", 1000, None, None)
        assert messages[1] == (
            8,
            "assistant",
            "旧回答 😀",
            2000,
            "已有公开推理\n" if with_metadata else None,
            '{ "inputTokens": 2, "totalTokens": 5 }' if with_metadata else None,
        )


async def test_failed_migration_rolls_back_columns_and_ledger(tmp_path: Path) -> None:
    database = tmp_path / "broken.sqlite"
    build_legacy_database(database, with_metadata=False)
    with sqlite3.connect(database) as connection:
        # 故意模拟外部同名但不兼容的表，使 002 建索引失败。
        connection.execute("CREATE TABLE agent_requests (unrelated TEXT)")
    with pytest.raises(MigrationError, match="已回滚"):
        await migrate_database(database)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(conversation_messages)")}
        assert "reasoning" not in columns
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'agent_schema_migrations'"
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT content FROM conversation_messages ORDER BY sequence"
        ).fetchall() == [
            ("  用户原始正文\n",),
            ("旧回答 😀",),
        ]


async def test_future_version_is_rejected_without_rewriting_data(tmp_path: Path) -> None:
    database = tmp_path / "future.sqlite"
    await migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO agent_schema_migrations VALUES (99, 0)")
    with pytest.raises(MigrationError, match="拒绝修改"):
        await migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version FROM agent_schema_migrations ORDER BY version"
        ).fetchall() == [
            (1,),
            (2,),
            (99,),
        ]


async def test_request_constraints_and_session_cascade(tmp_path: Path) -> None:
    database = tmp_path / "new.sqlite"
    await migrate_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO conversation_sessions VALUES ('s1', NULL, 1, 1)")
        insert = """INSERT INTO agent_requests (
            session_id, request_id, request_fingerprint, status, attempt, profile_id,
            response_json, error_code, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        running = ("s1", "r1", "v1:hash", "running", 1, "default", None, None, 1, 1)
        connection.execute(insert, running)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, running)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                insert, ("s1", "r2", "v1:hash", "succeeded", 1, "default", None, None, 1, 1)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                insert, ("missing", "r3", "v1:hash", "running", 1, "default", None, None, 1, 1)
            )
        connection.execute("DELETE FROM conversation_sessions WHERE session_id = ?", ("s1",))
        assert (
            connection.execute(
                "SELECT request_id FROM agent_requests WHERE session_id = ?", ("s1",)
            ).fetchall()
            == []
        )


async def test_legacy_orphan_messages_roll_back_entire_migration(tmp_path: Path) -> None:
    database = tmp_path / "orphan.sqlite"
    build_legacy_database(database, with_metadata=False)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?)",
            ("missing-session", 1, "user", "测试孤立消息", 1000),
        )
    with pytest.raises(MigrationError, match="失效的会话关联"):
        await migrate_database(database)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'agent_requests'"
            ).fetchone()
            is None
        )
