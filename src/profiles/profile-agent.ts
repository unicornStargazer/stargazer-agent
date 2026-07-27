/**
 * 按受控 Profile 选择 ChatAgent，并在首轮聊天前固化会话归属。
 *
 * 此处只编排 Profile 与现有聊天核心，不让 HTTP 或供应商细节进入 chat 包。
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

  /**
   * 异步聊天方法，处理用户与指定配置文件的对话
   * @param sessionId - 会话ID，用于标识当前对话
   * @param profileId - 可选的配置文件ID，如果未提供则使用绑定的配置文件
   * @param text - 用户输入的文本内容
   * @returns 返回ChatMessage类型的对话消息
   */
  async chat(sessionId: string, profileId: string | undefined, text: string): Promise<ChatMessage> {
    // 从会话存储中获取绑定的配置文件ID
    const boundProfileId = await this.conversationStore.profileId(sessionId);
    // 确定请求使用的配置文件ID，优先使用传入的profileId，其次使用绑定的配置文件ID，最后使用默认配置文件ID
    const requestedProfileId = profileId ?? boundProfileId ?? this.defaultProfileId;
    // 如果已绑定配置文件且与请求的配置文件不同，抛出配置文件冲突错误
    if (boundProfileId !== undefined && boundProfileId !== requestedProfileId) {
      throw new ConversationProfileConflictError();
    }
    // 获取请求的配置文件对象，如果不存在则抛出错误
    const profile = this.requireProfile(requestedProfileId);
    // 如果尚未绑定配置文件，则将当前配置文件绑定到会话
    if (boundProfileId === undefined) {
      await this.conversationStore.bindProfile(sessionId, profile.id);
    }
    // 使用对应的代理处理对话并返回结果
    return this.agentFor(profile).chat(sessionId, text);
  }

  async *chatStream(
    sessionId: string,
    profileId: string | undefined,
    text: string,
  ): AsyncGenerator<ModelStreamEvent> {
    const boundProfileId = await this.conversationStore.profileId(sessionId);
    const requestedProfileId = profileId ?? boundProfileId ?? this.defaultProfileId;
    if (boundProfileId !== undefined && boundProfileId !== requestedProfileId) {
      throw new ConversationProfileConflictError();
    }
    const profile = this.requireProfile(requestedProfileId);
    if (boundProfileId === undefined) {
      await this.conversationStore.bindProfile(sessionId, profile.id);
    }
    yield* this.agentFor(profile).chatStream(sessionId, text);
  }

  private agentFor(profile: AgentProfile): ChatAgent {
    const existingAgent = this.agentsByProfileId.get(profile.id);
    if (existingAgent !== undefined) {
      return existingAgent;
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
    if (!/^[a-zA-Z0-9_-]+$/.test(profile.id) || !profile.name.trim() || !profile.model.trim()) {
      throw new Error('Agent Profile 配置无效');
    }
    if (profilesById.has(profile.id)) {
      throw new Error(`Agent Profile 标识重复: ${profile.id}`);
    }
    profilesById.set(profile.id, profile);
  }
  return profilesById;
}
