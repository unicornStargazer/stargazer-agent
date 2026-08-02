/** 将 Profile 的基础提示与已选业务 Skill 组合为一次模型调用的系统提示。 */
import type { AgentSkill } from './skill-loader.js';

export function composeSystemPrompt(
  basePrompt: string | undefined,
  skills: readonly AgentSkill[],
): string | undefined {
  const sections = [basePrompt?.trim(), ...skills.map(formatSkill)].filter(
    (section): section is string => Boolean(section),
  );
  return sections.length === 0 ? undefined : sections.join('\n\n');
}

function formatSkill(skill: AgentSkill): string {
  return `<skill name="${escapeAttribute(skill.name)}">\n${skill.instructions}\n</skill>`;
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}
