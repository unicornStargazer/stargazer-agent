/**
 * Profile 到 ChatAgent 的领域编排。
 *
 * 它负责在首轮请求绑定会话 Profile，并按 Profile 缓存 Agent；
 * 不处理 HTTP 协议、供应商调用或数据库 SQL。
 */

import { ChatAgent } from '../chat/agent.js';
import type { ConversationProfileStore } from '../chat/conversation-store.js';
import type { ChatMessage } from '../chat/models.js';
import type { ChatModel, ModelStreamEvent } from '../chat/port.js';
import type { ToolRegistry } from '../tools/tool-registry.js';
import type { AgentProfile, AgentProfileSummary } from './agent-profile.js';
import { toAgentProfileSummary } from './agent-profile.js';

export class UnknownAgentProfileError extends Error {
  constructor(profileId: string) {
    super(`未知的 Agent Profile: ${profileId}`);
    this.name = 'UnknownAgentProfileError';
  }
}

export class ConversationProfileConflictError extends Error {
  constructor() {
    super('该会话已绑定其他 Agent Profile');
    this.name = 'ConversationProfileConflictError';
  }
}

export interface ProfileAgentOptions {
  readonly profiles: readonly AgentProfile[];
  readonly defaultProfileId: string;
  readonly conversationStore: ConversationProfileStore;
  readonly createModel: (profile: AgentProfile) => ChatModel;
  readonly tools?: ToolRegistry | undefined;
}

export class ProfileAgent {
  private readonly profilesById: ReadonlyMap<string, AgentProfile>;
  private readonly agentsByProfileId = new Map<string, ChatAgent>();
  private readonly defaultProfileId: string;
  private readonly conversationStore: ConversationProfileStore;
  private readonly createModel: (profile: AgentProfile) => ChatModel;
  private readonly tools: ToolRegistry | undefined;

  constructor(options: ProfileAgentOptions) {
    this.profilesById = createProfileMap(options.profiles);
    if (!this.profilesById.has(options.defaultProfileId)) {
      throw new Error('默认 Agent Profile 必须存在于注册表中');
    }

    this.defaultProfileId = options.defaultProfileId;
    this.conversationStore = options.conversationStore;
    this.createModel = options.createModel;
    this.tools = options.tools;
  }

  profiles(): readonly AgentProfileSummary[] {
    return [...this.profilesById.values()].map(toAgentProfileSummary);
  }

  defaultProfile(): AgentProfileSummary {
    return toAgentProfileSummary(this.requireProfile(this.defaultProfileId));
  }

  async chat(
    sessionId: string,
    requestedProfileId: string | undefined,
    text: string,
  ): Promise<ChatMessage> {
    const profile = await this.resolveSessionProfile(sessionId, requestedProfileId);
    return this.agentFor(profile).chat(sessionId, text);
  }

  async *chatStream(
    sessionId: string,
    requestedProfileId: string | undefined,
    text: string,
  ): AsyncGenerator<ModelStreamEvent> {
    const profile = await this.resolveSessionProfile(sessionId, requestedProfileId);
    yield* this.agentFor(profile).chatStream(sessionId, text);
  }

  /**
   * 会话首次使用 Profile 后即写入存储，后续请求不能静默切换，
   * 以避免同一段对话混入不同系统提示和模型。
   */
  private async resolveSessionProfile(
    sessionId: string,
    requestedProfileId: string | undefined,
  ): Promise<AgentProfile> {
    const boundProfileId = await this.conversationStore.profileId(sessionId);
    const selectedProfileId = requestedProfileId ?? boundProfileId ?? this.defaultProfileId;

    if (boundProfileId !== undefined && boundProfileId !== selectedProfileId) {
      throw new ConversationProfileConflictError();
    }

    const profile = this.requireProfile(selectedProfileId);
    if (boundProfileId === undefined) {
      await this.conversationStore.bindProfile(sessionId, profile.id);
    }
    return profile;
  }

  private agentFor(profile: AgentProfile): ChatAgent {
    const cachedAgent = this.agentsByProfileId.get(profile.id);
    if (cachedAgent !== undefined) {
      return cachedAgent;
    }

    const agent = new ChatAgent({
      model: this.createModel(profile),
      conversationStore: this.conversationStore,
      systemPrompt: profile.systemPrompt,
      historyLimit: profile.historyLimit,
      tools: this.tools,
    });
    this.agentsByProfileId.set(profile.id, agent);
    return agent;
  }

  private requireProfile(profileId: string): AgentProfile {
    const profile = this.profilesById.get(profileId);
    if (profile === undefined) {
      throw new UnknownAgentProfileError(profileId);
    }
    return profile;
  }
}

function createProfileMap(profiles: readonly AgentProfile[]): ReadonlyMap<string, AgentProfile> {
  if (profiles.length === 0) {
    throw new Error('至少需要一个 Agent Profile');
  }

  const profilesById = new Map<string, AgentProfile>();
  for (const profile of profiles) {
    assertValidProfile(profile);
    if (profilesById.has(profile.id)) {
      throw new Error(`Agent Profile 标识重复: ${profile.id}`);
    }
    profilesById.set(profile.id, profile);
  }
  return profilesById;
}

function assertValidProfile(profile: AgentProfile): void {
  if (!/^[a-zA-Z0-9_-]+$/.test(profile.id) || !profile.name.trim() || !profile.model.trim()) {
    throw new Error('Agent Profile 配置无效');
  }
}
