/**
 * 运行时配置的读取与校验。
 *
 * 本模块只解释环境变量，不创建网络连接、数据库连接或 Agent 实例，
 * 因此启动入口可以在装配前一次性发现配置错误。
 */

import { resolve } from 'node:path';

import type { AgentProfile } from '../profiles/index.js';

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3000;
const DEFAULT_DATABASE_FILE = 'stargazer-agent.sqlite';

export interface ModelProviderSettings {
  readonly apiKey: string;
  readonly baseUrl?: string | undefined;
  readonly includeStreamUsage?: boolean | undefined;
}

export interface ServerRuntimeConfiguration {
  readonly host: string;
  readonly port: number;
  readonly databasePath: string;
  readonly defaultModel: string;
  readonly provider: ModelProviderSettings;
  readonly agentProfiles: readonly AgentProfile[];
  readonly skillsDirectory?: string | undefined;
}

export function loadRuntimeConfiguration(): ServerRuntimeConfiguration {
  const defaultModel = requireEnvironment('OPENAI_MODEL');

  return {
    host: process.env.HOST?.trim() || DEFAULT_HOST,
    port: parsePort(process.env.PORT),
    databasePath: resolveDatabasePath(),
    defaultModel,
    provider: {
      apiKey: requireEnvironment('OPENAI_API_KEY'),
      baseUrl: optionalText(process.env.OPENAI_BASE_URL),
      includeStreamUsage: parseOptionalBoolean(process.env.OPENAI_STREAM_INCLUDE_USAGE),
    },
    agentProfiles: loadConfiguredAgentProfiles(defaultModel),
    skillsDirectory: optionalText(process.env.STARGAZER_SKILLS_DIR),
  };
}

function resolveDatabasePath(): string {
  const configuredDatabasePath = optionalText(process.env.STARGAZER_DATABASE_PATH);
  if (configuredDatabasePath !== undefined) {
    return resolve(process.cwd(), configuredDatabasePath);
  }

  const dataDirectory = optionalText(process.env.STARGAZER_DATA_DIR) ?? 'data';
  return resolve(process.cwd(), dataDirectory, DEFAULT_DATABASE_FILE);
}

function loadConfiguredAgentProfiles(defaultModel: string): readonly AgentProfile[] {
  const rawProfiles = optionalText(process.env.STARGAZER_AGENT_PROFILES);
  if (rawProfiles === undefined) {
    return [
      {
        id: 'default',
        name: '默认助手',
        model: defaultModel,
        systemPrompt: optionalText(process.env.STARGAZER_SYSTEM_PROMPT),
      },
    ];
  }

  const parsedProfiles = parseProfileList(rawProfiles);
  return parsedProfiles.map(parseAgentProfile);
}

function parseProfileList(value: string): unknown[] {
  try {
    const parsedValue = JSON.parse(value) as unknown;
    if (Array.isArray(parsedValue)) {
      return parsedValue;
    }
  } catch {
    // 统一使用下方错误，避免把原始配置内容输出到日志。
  }
  throw new Error('STARGAZER_AGENT_PROFILES 必须是 JSON 数组');
}

function parseAgentProfile(value: unknown): AgentProfile {
  if (!isRecord(value)) {
    throw new Error('Agent Profile 必须是对象');
  }

  const historyLimit = value.historyLimit;
  if (
    historyLimit !== undefined &&
    (typeof historyLimit !== 'number' || !Number.isSafeInteger(historyLimit) || historyLimit < 1)
  ) {
    throw new Error('Agent Profile historyLimit 必须是大于零的整数');
  }

  return {
    id: requireText(value.id, 'Agent Profile id'),
    name: requireText(value.name, 'Agent Profile name'),
    model: requireText(value.model, 'Agent Profile model'),
    systemPrompt:
      value.systemPrompt === undefined
        ? undefined
        : requireText(value.systemPrompt, 'Agent Profile systemPrompt'),
    historyLimit,
  };
}

function requireEnvironment(name: string): string {
  return requireText(process.env[name], name);
}

function requireText(value: unknown, fieldName: string): string {
  const text = optionalText(value);
  if (text === undefined) {
    throw new Error(`${fieldName} 不能为空`);
  }
  return text;
}

function optionalText(value: unknown): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalizedValue = value.trim();
  return normalizedValue || undefined;
}

function parsePort(value: string | undefined): number {
  if (optionalText(value) === undefined) {
    return DEFAULT_PORT;
  }

  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error('PORT 必须是 1 到 65535 之间的整数');
  }
  return port;
}

function parseOptionalBoolean(value: string | undefined): boolean | undefined {
  const normalizedValue = optionalText(value);
  if (normalizedValue === undefined) {
    return undefined;
  }
  if (normalizedValue === 'true') {
    return true;
  }
  if (normalizedValue === 'false') {
    return false;
  }
  throw new Error('OPENAI_STREAM_INCLUDE_USAGE 必须是 true 或 false');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
