#!/usr/bin/env node

/**
 * Application bootstrap entry point.
 * It builds infrastructure and the Fastify adapter; Agent domain modules remain framework-independent.
 */

import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ChatAgent } from './chat/index.js';
import { createHttpApp } from './http/app.js';
import { SqliteConversationStore } from './memory/index.js';
import { ProfileAgent } from './profiles/index.js';
import type { AgentProfile } from './profiles/index.js';
import { OpenAICompatibleChatModel } from './providers/index.js';
import { loadSkillProfiles } from './skills/index.js';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3000;
const DEFAULT_DATABASE_FILE = 'stargazer-agent.sqlite';

/**
 * 主函数，启动应用程序
 * @returns {Promise<number>} 返回状态码，0表示成功，2表示失败
 */
export async function main(): Promise<number> {
  try {
    // 获取环境变量中的模型名称
    const modelName = requireEnvironment('OPENAI_MODEL');
    // 解析数据库路径
    const databasePath = resolveDatabasePath();
    // 递归创建数据库所需的目录结构
    await mkdir(dirname(databasePath), { recursive: true });

    // 打开SQLite对话存储
    const conversationStore = await SqliteConversationStore.open({ databasePath });
    // 加载代理配置文件
    const profiles = await loadAgentProfiles(modelName);
    // 创建配置文件代理实例
    const profileAgent = new ProfileAgent({
      profiles,
      defaultProfileId: profiles[0]!.id,
      conversationStore,
      createModel: (profile) => createModel(profile.model),
    });
    // 创建聊天代理实例
    const agent = new ChatAgent({
      model: createModel(modelName),
      conversationStore,
      systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT,
    });
    // 创建HTTP应用实例
    const app = createHttpApp({
      agent,
      profileAgent,
      modelName,
      conversationStorage: 'sqlite',
    });
    // 添加关闭钩子，确保在应用关闭时正确关闭对话存储
    app.addHook('onClose', async () => conversationStore.close());

    // 获取主机地址，默认为DEFAULT_HOST
    const host = process.env.HOST?.trim() || DEFAULT_HOST;
    // 解析端口号
    const port = parsePort(process.env.PORT);
    // 启动HTTP服务器
    await app.listen({ host, port });
    // 输出启动信息
    process.stdout.write(`Stargazer Web 已启动: http://${host}:${String(port)}\n`);
    return 0;
  } catch (error) {
    // 输出错误信息
    process.stderr.write(`错误: ${errorMessage(error)}\n`);
    return 2;
  }
}

function createModel(model: string): OpenAICompatibleChatModel {
  return new OpenAICompatibleChatModel({
    apiKey: requireEnvironment('OPENAI_API_KEY'),
    model,
    baseUrl: process.env.OPENAI_BASE_URL,
    includeStreamUsage: parseOptionalBoolean(process.env.OPENAI_STREAM_INCLUDE_USAGE),
  });
}

function resolveDatabasePath(): string {
  const configuredDatabasePath = process.env.STARGAZER_DATABASE_PATH?.trim();
  if (configuredDatabasePath) {
    return resolve(process.cwd(), configuredDatabasePath);
  }
  const dataDirectory = process.env.STARGAZER_DATA_DIR?.trim() || 'data';
  return resolve(process.cwd(), dataDirectory, DEFAULT_DATABASE_FILE);
}

async function loadAgentProfiles(defaultModel: string): Promise<readonly AgentProfile[]> {
  const configuredProfiles = loadConfiguredAgentProfiles(defaultModel);
  const skillsDirectory = process.env.STARGAZER_SKILLS_DIR?.trim();
  if (!skillsDirectory) {
    return configuredProfiles;
  }
  const skillProfiles = await loadSkillProfiles({
    directory: resolve(process.cwd(), skillsDirectory),
    defaultModel,
  });
  return mergeAgentProfiles(configuredProfiles, skillProfiles);
}

function loadConfiguredAgentProfiles(defaultModel: string): readonly AgentProfile[] {
  const rawProfiles = process.env.STARGAZER_AGENT_PROFILES?.trim();
  if (!rawProfiles) {
    return [
      {
        id: 'default',
        name: '默认助手',
        model: defaultModel,
        systemPrompt: process.env.STARGAZER_SYSTEM_PROMPT,
      },
    ];
  }
  let value: unknown;
  try {
    value = JSON.parse(rawProfiles) as unknown;
  } catch {
    throw new Error('STARGAZER_AGENT_PROFILES 必须是 JSON 数组');
  }
  if (!Array.isArray(value)) {
    throw new Error('STARGAZER_AGENT_PROFILES 必须是 JSON 数组');
  }
  return value.map(parseAgentProfile);
}

function parseAgentProfile(value: unknown): AgentProfile {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Agent Profile 必须是对象');
  }
  const profile = value as Record<string, unknown>;
  const id = requireText(profile.id, 'Agent Profile id');
  const name = requireText(profile.name, 'Agent Profile name');
  const model = requireText(profile.model, 'Agent Profile model');
  const systemPrompt =
    profile.systemPrompt === undefined
      ? undefined
      : requireText(profile.systemPrompt, 'Agent Profile systemPrompt');
  const historyLimit = profile.historyLimit;
  if (
    historyLimit !== undefined &&
    (typeof historyLimit !== 'number' || !Number.isSafeInteger(historyLimit) || historyLimit < 1)
  ) {
    throw new Error('Agent Profile historyLimit 必须是大于零的整数');
  }
  return { id, name, model, systemPrompt, historyLimit };
}

function mergeAgentProfiles(
  configuredProfiles: readonly AgentProfile[],
  skillProfiles: readonly AgentProfile[],
): readonly AgentProfile[] {
  const profileIds = new Set(configuredProfiles.map((profile) => profile.id));
  for (const skillProfile of skillProfiles) {
    if (profileIds.has(skillProfile.id)) {
      throw new Error(`Skill ID conflicts with an Agent Profile: ${skillProfile.id}`);
    }
    profileIds.add(skillProfile.id);
  }
  return [...configuredProfiles, ...skillProfiles];
}

function requireEnvironment(name: string): string {
  return requireText(process.env[name], name);
}

function requireText(value: unknown, fieldName: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${fieldName} 不能为空`);
  }
  return value.trim();
}

function parsePort(value: string | undefined): number {
  if (value === undefined || !value.trim()) {
    return DEFAULT_PORT;
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('PORT 必须是 1 到 65535 之间的整数');
  }
  return port;
}

function parseOptionalBoolean(value: string | undefined): boolean | undefined {
  if (value === undefined || !value.trim()) {
    return undefined;
  }
  if (value === 'true') {
    return true;
  }
  if (value === 'false') {
    return false;
  }
  throw new Error('OPENAI_STREAM_INCLUDE_USAGE 必须是 true 或 false');
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const entryPath = process.argv[1];
if (entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
