/**
 * 使用 SQLite 保存服务端会话历史。
 *
 * 该实现负责单进程内的数据库初始化、事务和消息顺序；不负责用户身份、向量检索或跨进程协调。
 */

import { createRequire } from 'node:module';
import type { Database as SqliteDatabase } from 'sqlite3';

import {
  ConversationStoreError,
  normalizeConversationMessageLimit,
  normalizeConversationSessionId,
} from '../chat/conversation-store.js';
import type { ConversationProfileStore } from '../chat/conversation-store.js';
import { createChatMessage } from '../chat/models.js';
import type { ChatMessage, ChatRole } from '../chat/models.js';

const SQLITE_BUSY_TIMEOUT_MS = 5_000;
const require = createRequire(import.meta.url);
const sqlite3 = require('sqlite3') as { readonly Database: typeof SqliteDatabase };
const Database = sqlite3.Database;

const SCHEMA_SQL = `
  CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS conversation_messages (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES conversation_sessions (session_id) ON DELETE CASCADE
  );

  CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_sequence
    ON conversation_messages (session_id, sequence);
`;

interface MessageRow {
  readonly role: string;
  readonly content: string;
}

interface SequenceRow {
  readonly next_sequence: number;
}

interface TableColumnRow {
  readonly name: string;
}

export interface SqliteConversationStoreOptions {
  /** SQLite 数据库文件路径；由服务端配置决定，不能来自浏览器请求。 */
  readonly databasePath: string;
}

export class SqliteConversationStore implements ConversationProfileStore {
  private readonly database: SqliteDatabase;
  private operationTail: Promise<void> = Promise.resolve();
  private closed = false;

  private constructor(database: SqliteDatabase) {
    this.database = database;
  }

  /** 打开数据库并确保表、外键和锁等待策略已经就绪。 */
  static async open(options: SqliteConversationStoreOptions): Promise<SqliteConversationStore> {
    if (!options.databasePath.trim()) {
      throw new Error('SQLite 数据库路径不能为空');
    }

    const database = await openDatabase(options.databasePath);
    const store = new SqliteConversationStore(database);
    try {
      database.configure('busyTimeout', SQLITE_BUSY_TIMEOUT_MS);
      await execute(database, 'PRAGMA foreign_keys = ON');
      await executeScript(database, SCHEMA_SQL);
      await ensureProfileColumn(database);
      return store;
    } catch (error: unknown) {
      await closeDatabase(database).catch(() => undefined);
      throw toConversationStoreError('无法初始化会话存储', error);
    }
  }

  async messages(sessionId: string, limit?: number): Promise<readonly ChatMessage[]> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    const normalizedLimit = normalizeConversationMessageLimit(limit);
    return this.withOperation(async () => {
      const rows =
        normalizedLimit === undefined
          ? await query<MessageRow>(
              this.database,
              `SELECT role, content
               FROM conversation_messages
               WHERE session_id = ?
               ORDER BY sequence ASC`,
              [normalizedSessionId],
            )
          : await query<MessageRow>(
              this.database,
              `SELECT role, content
               FROM (
                 SELECT role, content, sequence
                 FROM conversation_messages
                 WHERE session_id = ?
                 ORDER BY sequence DESC
                 LIMIT ?
               )
               ORDER BY sequence ASC`,
              [normalizedSessionId, normalizedLimit],
            );
      return rows.map(toChatMessage);
    });
  }

  /**
   * 向指定会话追加消息的异步方法
   * @param sessionId 会话ID
   * @param messages 要追加的消息列表，只读数组
   * @returns Promise<void>
   */
  async append(sessionId: string, messages: readonly ChatMessage[]): Promise<void> {
    // 如果消息列表为空，直接返回
    if (messages.length === 0) {
      return;
    }

    // 规范化会话ID
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    // 验证消息是否可持久化
    assertPersistableMessages(messages);
    // 在操作上下文中执行数据库操作
    await this.withOperation(async () => {
      // 获取当前时间戳
      const timestamp = Date.now();
      // 开始立即事务
      await execute(this.database, 'BEGIN IMMEDIATE');
      try {
        // 插入或更新会话记录
        await execute(
          this.database,
          `INSERT INTO conversation_sessions (session_id, created_at_ms, updated_at_ms)
           VALUES (?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET updated_at_ms = excluded.updated_at_ms`,
          [normalizedSessionId, timestamp, timestamp],
        );
        // 查询下一个消息序列号
        const sequenceRow = await queryOne<SequenceRow>(
          this.database,
          `SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
           FROM conversation_messages
           WHERE session_id = ?`,
          [normalizedSessionId],
        );
        // 验证序列号有效性
        const nextSequence = sequenceRow?.next_sequence;
        if (nextSequence === undefined || !Number.isSafeInteger(nextSequence) || nextSequence < 0) {
          throw new Error('会话消息序列无效');
        }

        // 遍历消息列表并插入每条消息
        for (const [offset, message] of messages.entries()) {
          await execute(
            this.database,
            `INSERT INTO conversation_messages (session_id, sequence, role, content, created_at_ms)
             VALUES (?, ?, ?, ?, ?)`,
            [normalizedSessionId, nextSequence + offset, message.role, message.content, timestamp],
          );
        }
        // 提交事务
        await execute(this.database, 'COMMIT');
      } catch (error: unknown) {
        // 发生错误时回滚事务
        await rollback(this.database);
        throw error;
      }
    });
  }

  async clear(sessionId: string): Promise<void> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    await this.withOperation(async () => {
      await execute(this.database, 'DELETE FROM conversation_sessions WHERE session_id = ?', [
        normalizedSessionId,
      ]);
    });
  }

  /** 供进程关闭和隔离测试释放 SQLite 文件句柄；关闭后不再接受读写。 */
  async profileId(sessionId: string): Promise<string | undefined> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    return this.withOperation(async () => {
      const row = await queryOne<{ readonly profile_id: string | null }>(
        this.database,
        'SELECT profile_id FROM conversation_sessions WHERE session_id = ?',
        [normalizedSessionId],
      );
      return row?.profile_id ?? undefined;
    });
  }

  async bindProfile(sessionId: string, profileId: string): Promise<void> {
    const normalizedSessionId = normalizeConversationSessionId(sessionId);
    const normalizedProfileId = normalizeConversationSessionId(profileId);
    await this.withOperation(async () => {
      const timestamp = Date.now();
      await execute(this.database, 'BEGIN IMMEDIATE');
      try {
        const existing = await queryOne<{ readonly profile_id: string | null }>(
          this.database,
          'SELECT profile_id FROM conversation_sessions WHERE session_id = ?',
          [normalizedSessionId],
        );
        if (existing?.profile_id !== null && existing?.profile_id !== undefined) {
          if (existing.profile_id !== normalizedProfileId) {
            throw new Error('会话已绑定其他 Profile');
          }
        } else {
          await execute(
            this.database,
            `INSERT INTO conversation_sessions (session_id, profile_id, created_at_ms, updated_at_ms)
             VALUES (?, ?, ?, ?)
             ON CONFLICT(session_id) DO UPDATE SET profile_id = excluded.profile_id`,
            [normalizedSessionId, normalizedProfileId, timestamp, timestamp],
          );
        }
        await execute(this.database, 'COMMIT');
      } catch (error: unknown) {
        await rollback(this.database);
        throw error;
      }
    });
  }

  async close(): Promise<void> {
    await this.enqueue(async () => {
      if (this.closed) {
        return;
      }
      await closeDatabase(this.database);
      this.closed = true;
    });
  }

  private async withOperation<T>(operation: () => Promise<T>): Promise<T> {
    try {
      return await this.enqueue(async () => {
        if (this.closed) {
          throw new ConversationStoreError('会话存储已经关闭');
        }
        return operation();
      });
    } catch (error: unknown) {
      if (error instanceof ConversationStoreError) {
        throw error;
      }
      throw toConversationStoreError('会话存储不可用', error);
    }
  }

  /**
   * sqlite3 的回调 API 不会保留 async 调用顺序；单实例队列保证事务期间不会被同一连接的读写穿插。
   */
  private async enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const previousOperation = this.operationTail;
    let releaseOperation: (() => void) | undefined;
    this.operationTail = new Promise<void>((resolveOperation) => {
      releaseOperation = resolveOperation;
    });
    await previousOperation;
    try {
      return await operation();
    } finally {
      releaseOperation?.();
    }
  }
}

function assertPersistableMessages(messages: readonly ChatMessage[]): void {
  for (const message of messages) {
    if (message.role === 'system') {
      throw new Error('会话历史不能持久化系统提示');
    }
  }
}

function toChatMessage(row: MessageRow): ChatMessage {
  if (!isPersistedRole(row.role)) {
    throw new Error('会话历史包含未知消息角色');
  }
  return createChatMessage(row.role, row.content);
}

function isPersistedRole(role: string): role is Extract<ChatRole, 'user' | 'assistant'> {
  return role === 'user' || role === 'assistant';
}

function openDatabase(databasePath: string): Promise<SqliteDatabase> {
  return new Promise((resolveOpen, rejectOpen) => {
    const database = new Database(databasePath, (error) => {
      if (error === null) {
        resolveOpen(database);
        return;
      }
      rejectOpen(error);
    });
  });
}

/** 为已有数据库补齐 Profile 元数据列，保持 P0.1 创建的会话可直接升级。 */
async function ensureProfileColumn(database: SqliteDatabase): Promise<void> {
  const columns = await query<TableColumnRow>(database, 'PRAGMA table_info(conversation_sessions)');
  if (!columns.some((column) => column.name === 'profile_id')) {
    await execute(database, 'ALTER TABLE conversation_sessions ADD COLUMN profile_id TEXT');
  }
}

function closeDatabase(database: SqliteDatabase): Promise<void> {
  return new Promise((resolveClose, rejectClose) => {
    database.close((error) => {
      if (error === null) {
        resolveClose();
        return;
      }
      rejectClose(error);
    });
  });
}

function execute(
  database: SqliteDatabase,
  sql: string,
  parameters: readonly unknown[] = [],
): Promise<void> {
  return new Promise((resolveExecute, rejectExecute) => {
    database.run(sql, parameters, (error) => {
      if (error === null) {
        resolveExecute();
        return;
      }
      rejectExecute(error);
    });
  });
}

function executeScript(database: SqliteDatabase, sql: string): Promise<void> {
  return new Promise((resolveExecute, rejectExecute) => {
    database.exec(sql, (error) => {
      if (error === null) {
        resolveExecute();
        return;
      }
      rejectExecute(error);
    });
  });
}

function query<T>(
  database: SqliteDatabase,
  sql: string,
  parameters: readonly unknown[] = [],
): Promise<readonly T[]> {
  return new Promise((resolveQuery, rejectQuery) => {
    database.all<T>(sql, parameters, (error, rows) => {
      if (error === null) {
        resolveQuery(rows);
        return;
      }
      rejectQuery(error);
    });
  });
}

function queryOne<T>(
  database: SqliteDatabase,
  sql: string,
  parameters: readonly unknown[] = [],
): Promise<T | undefined> {
  return new Promise((resolveQuery, rejectQuery) => {
    database.get<T>(sql, parameters, (error, row) => {
      if (error === null) {
        resolveQuery(row);
        return;
      }
      rejectQuery(error);
    });
  });
}

async function rollback(database: SqliteDatabase): Promise<void> {
  await execute(database, 'ROLLBACK').catch(() => undefined);
}

function toConversationStoreError(message: string, cause: unknown): ConversationStoreError {
  return new ConversationStoreError(message, { cause });
}
