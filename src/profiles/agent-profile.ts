/** 定义由服务端维护、可安全返回给浏览器的 Agent Profile。 */

export interface AgentProfile {
  readonly id: string;
  readonly name: string;
  readonly model: string;
  readonly systemPrompt?: string | undefined;
  readonly historyLimit?: number | undefined;
}

/** 浏览器只需要展示此摘要，不能获得上游地址、密钥或完整系统提示。 */
export interface AgentProfileSummary {
  readonly id: string;
  readonly name: string;
  readonly model: string;
}

export function toAgentProfileSummary(profile: AgentProfile): AgentProfileSummary {
  return { id: profile.id, name: profile.name, model: profile.model };
}
