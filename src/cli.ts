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

function parseCommand(argumentsList: readonly string[]): ParsedCommand {
  if (argumentsList.length === 0 || argumentsList[0] === '--help' || argumentsList[0] === '-h') {
    return 'help';
  }
  if (argumentsList[0] !== 'chat') {
    throw new Error('未知命令，请使用 chat');
  }

  let message: string | undefined;
  let sessionId = DEFAULT_SESSION_ID;
  let systemPrompt: string | undefined;
  let model: string | undefined;
  let baseUrl: string | undefined;
  for (let index = 1; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index];
    if (argument === undefined) {
      throw new Error('命令参数不完整');
    }
    if (argument === '--help' || argument === '-h') {
      return 'help';
    }
    const optionValue = argumentsList[index + 1];
    if (optionValue === undefined) {
      throw new Error(`${argument} 缺少值`);
    }
    switch (argument) {
      case '--message':
        message = optionValue;
        break;
      case '--session-id':
        sessionId = optionValue;
        break;
      case '--system-prompt':
        systemPrompt = optionValue;
        break;
      case '--model':
        model = optionValue;
        break;
      case '--base-url':
        baseUrl = optionValue;
        break;
      default:
        throw new Error(`未知参数: ${argument}`);
    }
    index += 1;
  }
  return { message, sessionId, systemPrompt, model, baseUrl };
}

async function runChat(command: ChatCommand): Promise<number> {
  const agent = new ChatAgent({
    model: new OpenAICompatibleChatModel({
      apiKey: process.env.OPENAI_API_KEY ?? '',
      model: command.model ?? process.env.OPENAI_MODEL ?? '',
      baseUrl: command.baseUrl ?? process.env.OPENAI_BASE_URL,
    }),
    systemPrompt: command.systemPrompt,
  });
  if (command.message !== undefined) {
    const response = await agent.chat(command.sessionId, command.message);
    writeOutput(response.content);
    return 0;
  }
  return runInteractiveChat(agent, command.sessionId);
}

async function runInteractiveChat(agent: ChatAgent, sessionId: string): Promise<number> {
  const terminal = createInterface({ input: process.stdin, output: process.stdout });
  try {
    while (true) {
      const text = await terminal.question('you> ');
      if (text.trim() === '/exit' || text.trim() === '/quit') {
        return 0;
      }
      if (!text.trim()) {
        continue;
      }
      const response = await agent.chat(sessionId, text);
      writeOutput(`assistant> ${response.content}`);
    }
  } finally {
    terminal.close();
  }
}

function usageText(): string {
  return [
    '用法: stargazer-agent chat [选项]',
    '',
    '选项:',
    '  --message <text>         发送一条消息后退出',
    '  --session-id <id>        当前进程内的会话标识',
    '  --system-prompt <text>   每轮都会注入的系统提示',
    '  --model <name>           覆盖 OPENAI_MODEL',
    '  --base-url <url>         覆盖 OPENAI_BASE_URL',
  ].join('\n');
}

function writeOutput(message: string): void {
  process.stdout.write(`${message}\n`);
}

function writeError(message: string): void {
  process.stderr.write(`${message}\n`);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '发生未知错误';
}

const executedFile = process.argv[1];
if (executedFile !== undefined && import.meta.url === pathToFileURL(resolve(executedFile)).href) {
  void main().then((exitCode) => {
    process.exitCode = exitCode;
  });
}
