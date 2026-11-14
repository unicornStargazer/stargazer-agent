"""版本化、事务化迁移；仅在显式调用时操作指定数据库，不连接默认数据路径。"""

import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import aiosqlite


class MigrationError(RuntimeError):
    """结构不兼容或迁移失败；不回传数据库中的消息、凭据或 SQL 参数。"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    filename: str


CONVERSATIONS_MIGRATION = Migration(1, "001_conversations.sql")
REQUESTS_MIGRATION = Migration(2, "002_agent_requests.sql")
MIGRATIONS = (CONVERSATIONS_MIGRATION, REQUESTS_MIGRATION)


async def migrate_database(database_path: Path) -> tuple[int, ...]:
    """原子升级指定文件，返回本次版本；失败全量回滚，取消向上传播并关闭连接。"""
    try:
        connection_context = aiosqlite.connect(database_path, isolation_level=None, timeout=5)
        async with connection_context as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("BEGIN IMMEDIATE")
            try:
                applied = await _apply_pending_migrations(connection)
                await connection.commit()
                return applied
            except BaseException:
                # 包括取消：DDL 和版本记录必须一起撤销，不能留下半迁移状态。
                await connection.rollback()
                raise
    except sqlite3.Error:
        raise MigrationError("SQLite 迁移失败；原有事务已回滚，请在测试副本检查结构。") from None


async def _apply_pending_migrations(connection: aiosqlite.Connection) -> tuple[int, ...]:
    schema_sql = """CREATE TABLE IF NOT EXISTS agent_schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at_ms INTEGER NOT NULL
        )"""
    await connection.execute(schema_sql)
    cursor_context = connection.execute("SELECT version FROM agent_schema_migrations ORDER BY version")
    async with cursor_context as cursor:
        rows = await cursor.fetchall()
        versions = tuple(row[0] for row in rows)
    version_count = len(versions)
    expected_prefix = tuple(migration.version for migration in MIGRATIONS[:version_count])
    if versions != expected_prefix:
        raise MigrationError("迁移版本不连续或高于当前程序版本，拒绝修改数据库。")

    applied: list[int] = []
    for migration in MIGRATIONS[version_count:]:
        await _execute_script(connection, migration.filename)
        if migration.version == 1:
            await _upgrade_legacy_columns(connection)
        timestamp_ns = time.time_ns()
        parameters = (migration.version, timestamp_ns // 1_000_000)
        await connection.execute("INSERT INTO agent_schema_migrations(version, applied_at_ms) VALUES (?, ?)", parameters)
        applied.append(migration.version)

    cursor_context = connection.execute("PRAGMA foreign_key_check")
    async with cursor_context as cursor:
        row = await cursor.fetchone()
        if row is not None:
            raise MigrationError("旧库存在失效的会话关联，迁移已回滚。")
    applied_versions = tuple(applied)
    return applied_versions


async def _execute_script(connection: aiosqlite.Connection, filename: str) -> None:
    package = files("dokkan_agent.infrastructure.memory")
    resource = package.joinpath("migrations", filename)
    script = resource.read_text(encoding="utf-8")
    # executescript 会隐式提交；逐条执行以保持 DDL、兼容补列、版本记录在同一事务。
    statements = _split_statements(script)
    for statement in statements:
        await connection.execute(statement)


def _split_statements(script: str) -> Iterator[str]:
    pending = ""
    lines = script.splitlines(keepends=True)
    for line in lines:
        pending += line
        complete = sqlite3.complete_statement(pending)
        if complete:
            yield pending
            pending = ""
    remaining = pending.strip()
    if remaining:
        raise MigrationError("内置迁移脚本包含不完整的 SQL 语句。")


async def _upgrade_legacy_columns(connection: aiosqlite.Connection) -> None:
    """仅添加旧版本缺少的可空列；表名、列名和 DDL 都是服务端静态常量。"""
    # 同名残缺表不能被误记为已迁移，否则问题会延迟到首次用户请求才暴露。
    await connection.execute("SELECT session_id, created_at_ms, updated_at_ms FROM conversation_sessions LIMIT 0")
    await connection.execute("SELECT session_id, sequence, role, content, created_at_ms FROM conversation_messages LIMIT 0")
    cursor_context = connection.execute("PRAGMA table_info(conversation_sessions)")
    async with cursor_context as cursor:
        rows = await cursor.fetchall()
        session_columns = {row[1] for row in rows}
    cursor_context = connection.execute("PRAGMA table_info(conversation_messages)")
    async with cursor_context as cursor:
        rows = await cursor.fetchall()
        message_columns = {row[1] for row in rows}
    if "profile_id" not in session_columns:
        await connection.execute("ALTER TABLE conversation_sessions ADD COLUMN profile_id TEXT")
    if "reasoning" not in message_columns:
        await connection.execute("ALTER TABLE conversation_messages ADD COLUMN reasoning TEXT")
    if "usage_json" not in message_columns:
        await connection.execute("ALTER TABLE conversation_messages ADD COLUMN usage_json TEXT")
