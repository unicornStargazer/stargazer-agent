import { readFile, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';

import type { AgentProfile } from '../profiles/agent-profile.js';

const SKILL_FILE_NAME = 'SKILL.md';
const SKILL_ID_PATTERN = /^[a-zA-Z0-9_-]+$/;

export interface SkillProfileLoaderOptions {
  readonly directory: string;
  readonly defaultModel: string;
}


/**
 * 加载技能配置文件
 * @param options - 技能配置文件加载选项，包含目录路径和默认模型等信息
 * @returns 返回只读的代理配置文件数组
 */
export async function loadSkillProfiles(
  options: SkillProfileLoaderOptions, // 技能配置文件加载选项接口
): Promise<readonly AgentProfile[]> { // 返回只读的代理配置文件数组
  // 解析技能配置文件的目录路径
  const skillDirectory = resolve(options.directory);
  // 读取目录内容，包含文件类型信息
  const entries = await readdir(skillDirectory, { withFileTypes: true });
  // 使用Promise.all并行处理所有目录
  const profiles = await Promise.all(
    entries
      // 过滤出目录项
      .filter((entry) => entry.isDirectory())
      // 按目录名称排序
      .sort((first, second) => first.name.localeCompare(second.name))
      // 将每个目录映射为加载技能配置文件的操作
      .map(async (entry) =>
        loadSkillProfile(
          // 构建技能配置文件的完整路径
          join(skillDirectory, entry.name, SKILL_FILE_NAME),
          // 传入目录名称作为技能名称
          entry.name,
          // 使用默认模型
          options.defaultModel,
        ),
      ),
  );
  // 过滤掉undefined值，并确保返回类型正确
  return profiles.filter((profile): profile is AgentProfile => profile !== undefined);
}

/**
 * 加载技能配置文件
 * @param skillPath - 技能配置文件的路径
 * @param skillId - 技能的唯一标识符
 * @param defaultModel - 默认使用的模型
 * @returns 返回解析后的AgentProfile对象，如果文件不存在则返回undefined
 */
async function loadSkillProfile(
  skillPath: string,  // 技能配置文件的路径
  skillId: string,   // 技能的唯一标识符
  defaultModel: string, // 默认使用的模型
): Promise<AgentProfile | undefined> { // 返回类型：AgentProfile或undefined
  try {
    const content = await readFile(skillPath, 'utf8'); // 读取文件内容
    return parseSkillProfile(content, skillId, defaultModel, skillPath); // 解析技能配置文件
  } catch (error: unknown) { // 捕获可能的错误
    if (isFileNotFoundError(error)) { // 如果是文件未找到错误
      return undefined; // 返回undefined
    }
    throw error; // 其他错误则抛出
  }
}

/**
 * 解析技能配置文件，生成智能体配置档案
 * @param content 技能文档内容
 * @param skillId 技能ID
 * @param defaultModel 默认模型
 * @param skillPath 技能文件路径
 * @returns 返回解析后的智能体配置档案
 */
function parseSkillProfile(
  content: string,      // 技能文档内容字符串
  skillId: string,      // 技能标识符
  defaultModel: string, // 默认模型名称
  skillPath: string,    // 技能文件路径
): AgentProfile {        // 返回智能体配置档案类型
  // 检查技能ID是否符合规范模式
  if (!SKILL_ID_PATTERN.test(skillId)) {
    throw new Error(`Skill directory name is invalid: ${skillId}`);
  }
  // 分割技能文档的前置元数据和指令部分
  const { frontMatter, instructions } = splitSkillDocument(content, skillPath);
  // 解析前置元数据
  const attributes = parseFrontMatter(frontMatter, skillPath);
  // 获取必需的name属性
  const name = requireAttribute(attributes, 'name', skillPath);
  // 获取模型属性，如果不存在则使用默认模型
  const model = attributes.get('model') ?? requireText(defaultModel, 'default model');
  // 解析历史记录限制
  const historyLimit = parseHistoryLimit(attributes.get('historyLimit'), skillPath);
  // 返回完整的智能体配置档案对象
  return { id: skillId, name, model, systemPrompt: instructions, historyLimit };
}

/**
 * 将技能文档分割为前置元数据和指令部分
 * @param content 完整的技能文档内容
 * @param skillPath 技能文件路径，用于错误提示
 * @returns 返回包含frontMatter和instructions的对象
 */
function splitSkillDocument(
  content: string,
  skillPath: string,
): {
  readonly frontMatter: string;  // 只读的前置元数据部分
  readonly instructions: string; // 只读的指令部分
} {
  // 将所有回车换行符统一为换行符，确保跨平台一致性
  const normalizedContent = content.replace(/\r\n/g, '\n');
  // 检查文档是否以'---\n'开头，这是前置元数据的开始标记
  if (!normalizedContent.startsWith('---\n')) {
    throw new Error(`Skill file must start with front matter: ${skillPath}`);
  }
  // 查找前置元数据的结束标记位置
  const closingDelimiter = normalizedContent.indexOf('\n---\n', 4);
  // 如果找不到结束标记，抛出错误
  if (closingDelimiter < 0) {
    throw new Error(`Skill file front matter is not closed: ${skillPath}`);
  }
  // 提取指令部分，并去除首尾空白字符
  const instructions = normalizedContent.slice(closingDelimiter + 5).trim();
  // 检查指令部分是否为空
  if (!instructions) {
    throw new Error(`Skill instructions cannot be empty: ${skillPath}`);
  }
  // 返回分割后的前置元数据和指令
  return { frontMatter: normalizedContent.slice(4, closingDelimiter), instructions };
}

/**
 * 解析技能前置元数据（front matter）的函数
 * @param frontMatter - 包含技能元数据的字符串，格式为键值对，每行一个
 * @param skillPath - 技能文件的路径，用于错误提示
 * @returns 返回一个只读的Map，包含解析后的键值对属性
 * @throws 当元数据格式不正确或包含无效属性时抛出错误
 */
function parseFrontMatter(frontMatter: string, skillPath: string): ReadonlyMap<string, string> {
  // 创建一个新的Map来存储属性
  const attributes = new Map<string, string>();
  // 按行分割前置元数据字符串
  for (const line of frontMatter.split('\n')) {
    // 跳过空行
    if (!line.trim()) {
      continue;
    }
    // 查找键值分隔符（冒号）的位置
    const separatorIndex = line.indexOf(':');
    // 如果分隔符不存在或位置不正确（不能是第一个字符）
    if (separatorIndex < 1) {
      throw new Error(`Skill front matter has an invalid line: ${skillPath}`);
    }
    // 提取键和值，并去除前后空格
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    // 检查键是否为有效属性（name、model或historyLimit），值是否非空，以及键是否已存在
    if (!['name', 'model', 'historyLimit'].includes(key) || !value || attributes.has(key)) {
      throw new Error(`Skill front matter has an invalid attribute: ${skillPath}`);
    }
    // 将有效的键值对添加到Map中
    attributes.set(key, value);
  }
  // 返回只读的Map，确保数据不被修改
  return attributes;
}

/**
 * 检查并获取必需的属性值
 * @param attributes 属性的只读映射集合
 * @param name 需要获取的属性名称
 * @param skillPath 技能路径，用于错误提示
 * @returns 属性值
 * @throws 当属性不存在时抛出错误
 */
function requireAttribute(
  attributes: ReadonlyMap<string, string>, // 属性的只读映射集合
  name: string, // 需要获取的属性名称
  skillPath: string, // 技能路径，用于错误提示
): string { // 返回属性值
  const value = attributes.get(name); // 从属性集合中获取指定名称的值
  if (value === undefined) { // 如果值不存在
    throw new Error(`Skill front matter requires '${name}': ${skillPath}`); // 抛出错误，提示缺少必需属性
  }
  return value; // 返回获取到的属性值
}

function parseHistoryLimit(value: string | undefined, skillPath: string): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  const historyLimit = Number(value);
  if (!Number.isSafeInteger(historyLimit) || historyLimit < 1) {
    throw new Error(`Skill historyLimit must be a positive integer: ${skillPath}`);
  }
  return historyLimit;
}

function requireText(value: string, fieldName: string): string {
  const normalizedValue = value.trim();
  if (!normalizedValue) {
    throw new Error(`${fieldName} cannot be empty.`);
  }
  return normalizedValue;
}

function isFileNotFoundError(error: unknown): boolean {
  return (
    error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT'
  );
}
