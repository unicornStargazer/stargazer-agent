/** 验证 SQLite ConversationStore 的持久化、事务和会话隔离语义。 */

import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Database } from 'sqlite3';

import { afterEach, describe, expect, it } from 'vitest';

import {
  ChatAgent,
  ConversationStoreError,
  createAssistantMessage,
  createChatMessage,
} from '../../src/chat/index.js';
import { SqliteConversationStore } from '../../src/memory/index.js';
import { FakeChatModel } from '../../src/providers/index.js';

const openStores: SqliteConversationStore[] = [];
const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(openStores.splice(0).map((store) => store.close()));
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

describe('SqliteConversationStore', () => {
  it('在重新创建 Agent 后恢复历史并继续构造模型上下文', async () => {
    const databasePath = await createTemporaryDatabasePath();
    const firstStore = await openStore(databasePath);
    const firstAgent = new ChatAgent({
      model: new FakeChatModel(['第一轮回答']),
      conversationStore: firstStore,
    });
    await firstAgent.chat('session-a', '第一轮问题');
    await firstStore.close();
    removeOpenStore(firstStore);

    const resumedStore = await openStore(databasePath);
    const resumedModel = new FakeChatModel(['第二轮回答']);
    const resumedAgent = new ChatAgent({ model: resumedModel, conversationStore: resumedStore });

    await resumedAgent.chat('session-a', '第二轮问题');

    expect(resumedModel.requests).toEqual([
      [
        { role: 'user', content: '第一轮问题' },
        { role: 'assistant', content: '第一轮回答' },
        { role: 'user', content: '第二轮问题' },
      ],
    ]);
    await expect(resumedAgent.history('session-a')).resolves.toEqual([
      { role: 'user', content: '第一轮问题' },
      { role: 'assistant', content: '第一轮回答' },
      { role: 'user', content: '第二轮问题' },
      { role: 'assistant', content: '第二轮回答' },
    ]);
  });

  it('助手消息写入失败时回滚用户消息和会话元数据', async () => {
    const databasePath = await createTemporaryDatabasePath();
    const store = await openStore(databasePath);
    await executeSql(
      databasePath,
      `CREATE TRIGGER reject_assistant_message
       BEFORE INSERT ON conversation_messages
       WHEN NEW.role = 'assistant'
       BEGIN
         SELECT RAISE(ABORT, 'assistant insert rejected');
       END;`,
    );

    await expect(
      store.append('session-a', [
        createChatMessage('user', '需要持久化的问题'),
        createChatMessage('assistant', '不应落库的回答'),
      ]),
    ).rejects.toBeInstanceOf(ConversationStoreError);

    await expect(store.messages('session-a')).resolves.toEqual([]);
  });

  it('删除会话时级联删除消息且不会影响其他会话', async () => {
    const store = await openStore(await createTemporaryDatabasePath());
    await store.append('session-a', [createChatMessage('user', '会话 A')]);
    await store.append('session-b', [createChatMessage('user', '会话 B')]);

    await store.clear('session-a');

    await expect(store.messages('session-a')).resolves.toEqual([]);
    await expect(store.messages('session-b')).resolves.toEqual([
      { role: 'user', content: '会话 B' },
    ]);
  });

  it('窗口读取只返回最近消息并保持原始顺序', async () => {
    const store = await openStore(await createTemporaryDatabasePath());
    await store.append('session-a', [
      createChatMessage('user', '问题一'),
      createChatMessage('assistant', '回答一'),
      createChatMessage('user', '问题二'),
      createChatMessage('assistant', '回答二'),
    ]);

    await expect(store.messages('session-a', 2)).resolves.toEqual([
      { role: 'user', content: '问题二' },
      { role: 'assistant', content: '回答二' },
    ]);
  });

  it('重启后保留助手的思考过程与 Token 用量', async () => {
    const databasePath = await createTemporaryDatabasePath();
    const firstStore = await openStore(databasePath);
    await firstStore.append('session-a', [
      createChatMessage('user', '解释这个问题'),
      createAssistantMessage('这是回答', '先分析边界条件', {
        inputTokens: 12,
        outputTokens: 20,
        reasoningTokens: 8,
        totalTokens: 32,
      }),
    ]);
    await firstStore.close();
    removeOpenStore(firstStore);

    const resumedStore = await openStore(databasePath);

    await expect(resumedStore.messages('session-a')).resolves.toEqual([
      { role: 'user', content: '解释这个问题' },
      {
        role: 'assistant',
        content: '这是回答',
        reasoning: '先分析边界条件',
        usage: { inputTokens: 12, outputTokens: 20, reasoningTokens: 8, totalTokens: 32 },
      },
    ]);
  });
});

async function createTemporaryDatabasePath(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'stargazer-agent-memory-'));
  temporaryDirectories.push(directory);
  return join(directory, 'conversation.sqlite');
}

async function openStore(databasePath: string): Promise<SqliteConversationStore> {
  const store = await SqliteConversationStore.open({ databasePath });
  openStores.push(store);
  return store;
}

function removeOpenStore(store: SqliteConversationStore): void {
  const storeIndex = openStores.indexOf(store);
  if (storeIndex >= 0) {
    openStores.splice(storeIndex, 1);
  }
}

function executeSql(databasePath: string, sql: string): Promise<void> {
  return new Promise((resolveExecute, rejectExecute) => {
    const database = new Database(databasePath, (openError) => {
      if (openError !== null) {
        rejectExecute(openError);
        return;
      }
      database.exec(sql, (executeError) => {
        database.close((closeError) => {
          if (executeError !== null) {
            rejectExecute(executeError);
            return;
          }
          if (closeError !== null) {
            rejectExecute(closeError);
            return;
          }
          resolveExecute();
        });
      });
    });
  });
}
