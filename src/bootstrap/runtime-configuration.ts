/**
 * 服务端运行配置的文件加载与校验。
 *
 * 配置只从项目内的 JSON 文件读取，浏览器永远无法修改 Provider 凭据、模型地址或模型清单。
 */

import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

import type { AgentProfile } from '../profiles/index.js';

const DEFAULT_CONFIGURATION_PATH = resolve(process.cwd(), 'config', 'stargazer-agent.json');

export interface ModelProviderSettings {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly includeStreamUsage: boolean;
}

export interface ServerRuntimeConfiguration {
  readonly host: string;
  readonly port: number;
  readonly databasePath: string;
  readonly defaultModel: string;
  readonly defaultProfileId: string;
  readonly provider: ModelProviderSettings;
  readonly agentProfiles: readonly AgentProfile[];
  readonly skillsDirectory?: string | undefined;
}

/** 默认从 config/stargazer-agent.json 加载；修改文件后需要重启服务。 */
export async function loadRuntimeConfiguration(): Promise<ServerRuntimeConfiguration> {
  const configurationPath = DEFAULT_CONFIGURATION_PATH;
  const rawConfiguration = await readConfigurationFile(configurationPath);
  return parseConfiguration(rawConfiguration);
}

async function readConfigurationFile(configurationPath: string): Promise<unknown> {
  let content: string;
  try {
    content = await readFile(configurationPath, 'utf8');
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`无法读取配置文件 ${configurationPath}: ${reason}`);
  }

  try {
    return JSON.parse(content) as unknown;
  } catch {
    throw new Error(`配置文件不是有效 JSON: ${configurationPath}`);
  }
}

function parseConfiguration(value: unknown): ServerRuntimeConfiguration {
  const root = requireRecord(value, '配置文件根节点必须是对象');
  const server = requireRecord(root.server, 'server 必须是对象');
  const storage = requireRecord(root.storage, 'storage 必须是对象');
  const provider = requireRecord(root.provider, 'provider 必须是对象');
  const agents = requireRecord(root.agents, 'agents 必须是对象');
  const agentProfiles = requireProfileList(agents.profiles);
  const defaultProfileId = requireText(agents.defaultProfileId, 'agents.defaultProfileId');

  if (!agentProfiles.some((profile) => profile.id === defaultProfileId)) {
    throw new Error('agents.defaultProfileId 必须引用 agents.profiles 中的配置项');
  }

  const defaultProfile = agentProfiles.find((profile) => profile.id === defaultProfileId);
  return {
    host: requireText(server.host, 'server.host'),
    port: parsePort(server.port),
    databasePath: resolve(process.cwd(), requireText(storage.databasePath, 'storage.databasePath')),
    defaultModel: defaultProfile!.model,
    defaultProfileId,
    provider: {
      apiKey: requireText(provider.apiKey, 'provider.apiKey'),
      baseUrl: requireText(provider.baseUrl, 'provider.baseUrl'),
      includeStreamUsage: requireBoolean(
        provider.includeStreamUsage,
        'provider.includeStreamUsage',
      ),
    },
    agentProfiles,
    skillsDirectory: optionalText(root.skillsDirectory, 'skillsDirectory'),
  };
}

function requireProfileList(value: unknown): readonly AgentProfile[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error('agents.profiles 必须是非空数组');
  }

  const profiles = value.map(parseAgentProfile);
  const profileIds = new Set<string>();
  for (const profile of profiles) {
    if (profileIds.has(profile.id)) {
      throw new Error(`agents.profiles 包含重复 id: ${profile.id}`);
    }
    profileIds.add(profile.id);
  }
  return profiles;
}

function parseAgentProfile(value: unknown): AgentProfile {
  const profile = requireRecord(value, 'agents.profiles 的每项必须是对象');
  const historyLimit = profile.historyLimit;
  if (
    historyLimit !== undefined &&
    (typeof historyLimit !== 'number' || !Number.isSafeInteger(historyLimit) || historyLimit < 1)
  ) {
    throw new Error('Agent Profile historyLimit 必须是大于零的整数');
  }
  return {
    id: requireIdentifier(profile.id, 'Agent Profile id'),
    name: requireText(profile.name, 'Agent Profile name'),
    model: requireText(profile.model, 'Agent Profile model'),
    systemPrompt:
      profile.systemPrompt === undefined
        ? undefined
        : requireText(profile.systemPrompt, 'Agent Profile systemPrompt'),
    historyLimit,
  };
}

function parsePort(value: unknown): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 65_535) {
    throw new Error('server.port 必须是 1 到 65535 之间的整数');
  }
  return value;
}

function requireBoolean(value: unknown, fieldName: string): boolean {
  if (typeof value !== 'boolean') {
    throw new Error(`${fieldName} 必须是布尔值`);
  }
  return value;
}

function requireIdentifier(value: unknown, fieldName: string): string {
  const identifier = requireText(value, fieldName);
  if (!/^[a-zA-Z0-9_-]+$/.test(identifier)) {
    throw new Error(`${fieldName} 格式不正确`);
  }
  return identifier;
}

function requireText(value: unknown, fieldName: string): string {
  const text = optionalText(value, fieldName);
  if (text === undefined) {
    throw new Error(`${fieldName} 不能为空`);
  }
  return text;
}

function optionalText(value: unknown, fieldName: string): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== 'string') {
    throw new Error(`${fieldName} 必须是字符串`);
  }
  const normalizedValue = value.trim();
  return normalizedValue || undefined;
}

function requireRecord(value: unknown, errorMessage: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(errorMessage);
  }
  return value as Record<string, unknown>;
}
