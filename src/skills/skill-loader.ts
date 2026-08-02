/**
 * 业务 Skill 的文件加载边界。
 *
 * 本模块只将 SKILL.md 转换为业务指令，不负责模型、上下文窗口或工具权限。
 * 这些运行时决策由 Agent Profile 和服务端装配统一管理。
 */
import { readFile, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const SKILL_FILE_NAME = 'SKILL.md';
const SKILL_ID_PATTERN = /^[a-zA-Z0-9_-]+$/;
const SKILL_ATTRIBUTE_NAMES = new Set(['name']);
const FORBIDDEN_SKILL_ATTRIBUTE_NAMES = new Set(['model', 'historyLimit']);

export interface AgentSkill {
  readonly id: string;
  readonly name: string;
  readonly instructions: string;
}

export interface SkillLoaderOptions {
  readonly directory: string;
}

export async function loadAgentSkills(
  options: SkillLoaderOptions,
): Promise<readonly AgentSkill[]> {
  const skillDirectory = resolve(options.directory);
  const entries = await readdir(skillDirectory, { withFileTypes: true });
  const skills = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory())
      .sort((first, second) => first.name.localeCompare(second.name))
      .map((entry) => loadAgentSkill(join(skillDirectory, entry.name, SKILL_FILE_NAME), entry.name)),
  );
  return skills.filter((skill): skill is AgentSkill => skill !== undefined);
}

async function loadAgentSkill(
  skillPath: string,
  skillId: string,
): Promise<AgentSkill | undefined> {
  try {
    return parseAgentSkill(await readFile(skillPath, 'utf8'), skillId, skillPath);
  } catch (error: unknown) {
    if (isFileNotFoundError(error)) {
      return undefined;
    }
    throw error;
  }
}

function parseAgentSkill(content: string, skillId: string, skillPath: string): AgentSkill {
  if (!SKILL_ID_PATTERN.test(skillId)) {
    throw new Error(`Skill directory name is invalid: ${skillId}`);
  }

  const { frontMatter, instructions } = splitSkillDocument(content, skillPath);
  const attributes = parseFrontMatter(frontMatter, skillPath);
  const name = attributes.get('name');
  if (name === undefined) {
    throw new Error(`Skill front matter requires 'name': ${skillPath}`);
  }
  return { id: skillId, name, instructions };
}

function splitSkillDocument(
  content: string,
  skillPath: string,
): { readonly frontMatter: string; readonly instructions: string } {
  const normalizedContent = content.replace(/\r\n/g, '\n');
  if (!normalizedContent.startsWith('---\n')) {
    throw new Error(`Skill file must start with front matter: ${skillPath}`);
  }
  const closingDelimiter = normalizedContent.indexOf('\n---\n', 4);
  if (closingDelimiter < 0) {
    throw new Error(`Skill file front matter is not closed: ${skillPath}`);
  }
  const instructions = normalizedContent.slice(closingDelimiter + 5).trim();
  if (!instructions) {
    throw new Error(`Skill instructions cannot be empty: ${skillPath}`);
  }
  return { frontMatter: normalizedContent.slice(4, closingDelimiter), instructions };
}

function parseFrontMatter(frontMatter: string, skillPath: string): ReadonlyMap<string, string> {
  const attributes = new Map<string, string>();
  for (const line of frontMatter.split('\n')) {
    if (!line.trim()) {
      continue;
    }
    const separatorIndex = line.indexOf(':');
    if (separatorIndex < 1) {
      throw new Error(`Skill front matter has an invalid line: ${skillPath}`);
    }
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    if (FORBIDDEN_SKILL_ATTRIBUTE_NAMES.has(key)) {
      throw new Error(`Skill '${key}' is not allowed; configure it in agents.profiles: ${skillPath}`);
    }
    if (!SKILL_ATTRIBUTE_NAMES.has(key) || !value || attributes.has(key)) {
      throw new Error(`Skill front matter has an invalid attribute: ${skillPath}`);
    }
    attributes.set(key, value);
  }
  return attributes;
}

function isFileNotFoundError(error: unknown): boolean {
  return (
    error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT'
  );
}
