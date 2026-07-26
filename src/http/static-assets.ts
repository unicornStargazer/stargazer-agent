/** 同源静态资源服务与路径穿越防护。 */

import { readFile } from 'node:fs/promises';
import type { ServerResponse } from 'node:http';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';

import { HttpError, writeSecurityHeaders } from './http-error.js';

const CONTENT_TYPES: Readonly<Record<string, string>> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};

export async function serveStaticAsset(
  response: ServerResponse,
  method: string,
  pathname: string,
  publicDirectory: string,
): Promise<void> {
  if (method !== 'GET' && method !== 'HEAD') {
    throw new HttpError(405, 'METHOD_NOT_ALLOWED', '该资源不支持当前请求方法。');
  }
  const { filePath, relativePath } = resolveStaticAsset(publicDirectory, pathname);
  let content: Buffer;
  try {
    content = await readFile(filePath);
  } catch (error: unknown) {
    if (isFileNotFoundError(error)) throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
    throw new HttpError(500, 'ASSET_UNAVAILABLE', '页面资源暂时不可用。');
  }
  writeSecurityHeaders(response);
  response.writeHead(200, {
    'Cache-Control': relativePath.startsWith(`assets${sep}`)
      ? 'public, max-age=31536000, immutable'
      : 'no-cache',
    'Content-Length': content.byteLength,
    'Content-Type': CONTENT_TYPES[extname(filePath).toLowerCase()] ?? 'application/octet-stream',
  });
  response.end(method === 'HEAD' ? undefined : content);
}

function resolveStaticAsset(
  publicDirectory: string,
  pathname: string,
): { readonly filePath: string; readonly relativePath: string } {
  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(pathname);
  } catch {
    throw new HttpError(400, 'INVALID_PATH', '资源路径格式不正确。');
  }
  const filePath = resolve(
    publicDirectory,
    `.${decodedPath === '/' ? '/index.html' : decodedPath}`,
  );
  const relativePath = relative(publicDirectory, filePath);
  if (
    relativePath === '..' ||
    relativePath.startsWith(`..${sep}`) ||
    isAbsolute(relativePath) ||
    relativePath.includes('\u0000')
  ) {
    throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
  }
  return { filePath, relativePath };
}

function isFileNotFoundError(error: unknown): boolean {
  return (
    error instanceof Error &&
    'code' in error &&
    ['ENOENT', 'EISDIR'].includes((error as NodeJS.ErrnoException).code ?? '')
  );
}
