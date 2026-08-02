/**
 * 服务端组合根。
 *
 * 只在这里选择 SQLite、OpenAI 兼容 Provider 与 Fastify 等具体实现；
 * chat、application 等核心模块不依赖该装配细节。
 */

import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

import type { FastifyInstance } from 'fastify';

import { ChatAgent } from '../chat/index.js';
import { createHttpApp } from '../http/app.js';
import { SqliteConversationStore } from '../memory/index.js';
import { ProfileAgent } from '../profiles/index.js';
import type { AgentProfile } from '../profiles/index.js';
import { OpenAICompatibleChatModel } from '../providers/index.js';
import { composeSystemPrompt, loadAgentSkills } from '../skills/index.js';
import { createDefaultToolRegistry } from '../tools/index.js';
import {
  loadRuntimeConfiguration,
  type ModelProviderSettings,
  type ServerRuntimeConfiguration,
} from './runtime-configuration.js';

export interface ServerApplication {
  readonly app: FastifyInstance;
  readonly host: string;
  readonly port: number;
}

export async function createServerApplication(): Promise<ServerApplication> {
  const configuration = await loadRuntimeConfiguration();
  await mkdir(dirname(configuration.databasePath), { recursive: true });

  const conversationStore = await SqliteConversationStore.open({
    databasePath: configuration.databasePath,
  });
  const profiles = await loadAgentProfiles(configuration);
  const defaultProfile = profiles.find((profile) => profile.id === configuration.defaultProfileId);
  if (defaultProfile === undefined) {
    throw new Error('默认 Agent Profile 不存在');
  }
  const createModel = createModelFactory(configuration.provider);
  const tools = createDefaultToolRegistry();
  const profileAgent = new ProfileAgent({
    profiles,
    defaultProfileId: configuration.defaultProfileId,
    conversationStore,
    createModel: (profile) => createModel(profile.model),
    tools,
  });
  const agent = new ChatAgent({
    model: createModel(configuration.defaultModel),
    conversationStore,
    systemPrompt: defaultProfile.systemPrompt,
    tools,
  });
  const app = createHttpApp({
    agent,
    profileAgent,
    modelName: configuration.defaultModel,
    conversationStorage: 'sqlite',
  });

  app.addHook('onClose', async () => conversationStore.close());
  return { app, host: configuration.host, port: configuration.port };
}

function createModelFactory(settings: ModelProviderSettings) {
  return (model: string): OpenAICompatibleChatModel =>
    new OpenAICompatibleChatModel({
      apiKey: settings.apiKey,
      model,
      baseUrl: settings.baseUrl,
      includeStreamUsage: settings.includeStreamUsage,
    });
}

async function loadAgentProfiles(
  configuration: ServerRuntimeConfiguration,
): Promise<readonly AgentProfile[]> {
  const skills =
    configuration.skillsDirectory === undefined
      ? []
      : await loadAgentSkills({ directory: resolve(process.cwd(), configuration.skillsDirectory) });
  return configuration.agentProfiles.map((profile) => ({
    ...profile,
    systemPrompt: composeSystemPrompt(profile.systemPrompt, skills),
  }));
}
