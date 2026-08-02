#!/usr/bin/env node

/**
 * HTTP 服务的可执行入口。
 *
 * 运行时依赖的创建集中在 bootstrap；本文件只负责启动进程和输出启动结果。
 */

import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

import { createServerApplication } from './bootstrap/server-application.js';

export async function main(): Promise<number> {
  try {
    const application = await createServerApplication();
    await application.app.listen({ host: application.host, port: application.port });
    process.stdout.write(
      `Stargazer Web 已启动: http://${application.host}:${String(application.port)}\n`,
    );
    return 0;
  } catch (error) {
    process.stderr.write(`错误: ${errorMessage(error)}\n`);
    return 2;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const entryPath = process.argv[1];
if (entryPath !== undefined && resolve(entryPath) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
