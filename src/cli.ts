#!/usr/bin/env node

/**
 * 提供标准文本 Agent 的命令行入口。
 *
 * 负责读取参数和环境变量、创建 ChatAgent 并展示文本回复；不保存跨进程会话、不记录 API Key、
 * 不处理工具调用。允许依赖 chat、providers 与 Node.js 终端模块。
 */

import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline/promises';

import { ChatAgent } from './chat/index.js';
import { OpenAICompatibleChatModel } from './providers/index.js';

const DEFAULT_SESSION_ID = 'default';

interface ChatCommand {
  readonly message: string | undefined;
  readonly sessionId: string;
  readonly systemPrompt: string | undefined;
  readonly model: string | undefined;
  readonly baseUrl: string | undefined;
}

type ParsedCommand = ChatCommand | 'help';

/** 运行 CLI 并返回进程退出码；预期的配置与模型错误不会输出堆栈。 */
export async function main(
  argumentsList: readonly string[] = process.argv.slice(2),
): Promise<number> {
  try {
    const command = parseCommand(argumentsList);
    if (command === 'help') {
      writeOutput(usageText());
      return 0;
    }
    return await runChat(command);
  } catch (error: unknown) {
    writeError(`错误: ${errorMessage(error)}`);
    return 2;
  }
}

/**
 * 解析命令行参数并返回解析后的命令对象
 * @param argumentsList - 只读的字符串数组，包含命令行参数
 * @returns 返回解析后的命令，可能是字符串 'help' 或包含各种选项的对象
 */
function parseCommand(argumentsList: readonly string[]): ParsedCommand {
  // 检查是否为空参数或请求帮助
  if (argumentsList.length === 0 || argumentsList[0] === '--help' || argumentsList[0] === '-h') {
    return 'help';
  }
  // 检查第一个参数是否为 'chat' 命令
  if (argumentsList[0] !== 'chat') {
    throw new Error('未知命令，请使用 chat');
  }

  let message: string | undefined; // 存储消息内容
  let sessionId = DEFAULT_SESSION_ID; // 存储会话ID，默认值为 DEFAULT_SESSION_ID
  let systemPrompt: string | undefined; // 存储系统提示
  let model: string | undefined; // 存储模型名称
  let baseUrl: string | undefined; // 存储基础URL
  // 遍历参数列表，从第二个参数开始（第一个参数是命令本身）
  for (let index = 1; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument === undefined) {
      throw new Error('命令参数不完整');
    }
    // 如果遇到帮助参数，直接返回帮助
    if (argument === '--help' || argument === '-h') {
      return 'help';
    }
    // 获取当前参数的下一个参数作为值
    const optionValue = argumentsList[index + 1];
    if (optionValue === undefined) {
      throw new Error(`${argument} 缺少值`);
    }
    // 根据参数类型进行相应处理
    switch (argument) {
      case '--message':
        message = optionValue; // 设置消息内容
        break;
      case '--session-id':
        sessionId = optionValue; // 设置会话ID
        break;
      case '--system-prompt':
        systemPrompt = optionValue; // 设置系统提示
        break;
      case '--model':
        model = optionValue; // 设置模型名称
        break;
      case '--base-url':
        baseUrl = optionValue; // 设置基础URL
        break;
      default:
        throw new Error(`未知参数: ${argument}`);
    }
    index += 1; // 跳过已经处理过的值
  }
  // 返回包含所有解析选项的对象
  return { message, sessionId, systemPrompt, model, baseUrl };
}

/**
 * 运行聊天交互的主函数
 * @param command - 包含聊天命令相关参数的对象
 * @returns 返回一个Promise，解析为状态码（0表示成功）
 */
async function runChat(command: ChatCommand): Promise<number> {
  // 创建聊天代理实例，配置模型和系统提示
  const agent = new ChatAgent({
    model: new OpenAICompatibleChatModel({
      apiKey: process.env.OPENAI_API_KEY ?? '', // 从环境变量获取API密钥，如果未设置则为空字符串
      model: command.model ?? process.env.OPENAI_MODEL ?? '', // 使用命令中的模型或环境变量中的模型，如果都未设置则为空字符串
      baseUrl: command.baseUrl ?? process.env.OPENAI_BASE_URL, // 使用命令中的基础URL或环境变量中的URL
    }),
    systemPrompt: command.systemPrompt, // 设置系统提示
  });
  // 如果命令中包含消息，则直接发送消息并获取响应
  if (command.message !== undefined) {
    const response = await agent.chat(command.sessionId, command.message); // 发送消息并获取响应
    writeOutput(response.content); // 将响应内容写入输出
    return 0; // 返回成功状态码
  }
  // 如果没有提供消息，则运行交互式聊天模式
  return runInteractiveChat(agent, command.sessionId);
}

/**
 * 运行一个交互式聊天会话
 * @param agent 聊天代理对象，用于处理聊天交互
 * @param sessionId 会话ID，用于标识特定的聊天会话
 * @returns 返回一个Promise，解析为退出码（0表示正常退出）
 */
async function runInteractiveChat(agent: ChatAgent, sessionId: string): Promise<number> {
  // 创建一个终端接口，用于处理标准输入和输出
  const terminal = createInterface({ input: process.stdin, output: process.stdout });
  try {
    // 无限循环，持续处理用户输入
    while (true) {
      // 等待用户输入，并显示提示符 "you> "
      const text = await terminal.question('you> ');
      // 检查用户是否输入了退出命令
      if (text.trim() === '/exit' || text.trim() === '/quit') {
        return 0; // 返回退出码0，表示正常退出
      }
      // 如果输入为空，则跳过当前循环
      if (!text.trim()) {
        continue;
      }
      // 使用代理对象处理用户输入，并获取响应
      const response = await agent.chat(sessionId, text);
      // 将助手的响应输出到终端，前面加上提示符 "assistant> "
      writeOutput(`assistant> ${response.content}`);
    }
  } finally {
    // 确保在函数退出时关闭终端接口
    terminal.close();
  }
}

/**
 * 返回命令行工具的使用说明文本
 * @returns {string} 格式化后的帮助信息，包含所有可用选项及其说明
 */
function usageText(): string {
  return [
    '用法: stargazer-agent chat [选项]', // 基本命令格式说明
    '', // 空行，用于分隔不同部分
    '选项:', // "选项"标题
    '  --message <text>         发送一条消息后退出', // 发送消息选项
    '  --session-id <id>        当前进程内的会话标识', // 会话ID选项
    '  --system-prompt <text>   每轮都会注入的系统提示', // 系统提示选项
    '  --model <name>           覆盖 OPENAI_MODEL', // 模型名称选项
    '  --base-url <url>         覆盖 OPENAI_BASE_URL', // API基础URL选项
  ].join('\n'); // 使用换行符连接数组元素
}

/**
 * 向标准输出写入消息的函数
 * @param message - 要输出的字符串消息
 */
function writeOutput(message: string): void {
  // 使用process.stdout.write输出消息，并在末尾添加换行符
  process.stdout.write(`${message}\n`);
}

function writeError(message: string): void {
  process.stderr.write(`${message}\n`);
}

/**
 * 处理错误信息，将未知错误转换为字符串
 * @param error - 需要处理的错误对象，类型为unknown
 * @returns 返回错误信息的字符串，如果是Error实例则返回其message，否则返回默认错误信息
 */
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '发生未知错误';
}

const executedFile = process.argv[1];
if (executedFile !== undefined && import.meta.url === pathToFileURL(resolve(executedFile)).href) {
  void main().then((exitCode) => {
    process.exitCode = exitCode;
  });
}
