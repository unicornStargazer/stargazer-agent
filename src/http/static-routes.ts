/** 静态资源路由独立管理缓存语义与路径穿越防护。 */

import fastifyStatic from '@fastify/static';
import type { FastifyInstance, FastifyReply } from 'fastify';
import { resolve } from 'node:path';

import { HttpError } from './http-error.js';

export function registerStaticRoutes(
  app: FastifyInstance,
  configuredDirectory: string | undefined,
): void {
  const publicDirectory = resolve(configuredDirectory ?? resolve(process.cwd(), 'web', 'dist'));
  void app.register(fastifyStatic, { root: publicDirectory, serve: false });

  app.get('/', async (_request, reply) => sendStaticFile(reply, 'index.html'));
  app.get<{ Params: { readonly '*': string } }>('/*', async (request, reply) => {
    const path = request.params['*'];
    if (!path || path.startsWith('api/') || isUnsafePath(path, request.raw.url)) {
      throw new HttpError(404, 'NOT_FOUND', '请求的资源不存在。');
    }
    return sendStaticFile(reply, path);
  });
}

function isUnsafePath(path: string, rawUrl: string | undefined): boolean {
  const rawPath = rawUrl?.split('?', 1)[0] ?? path;
  try {
    return decodeURIComponent(rawPath).replaceAll('\\', '/').split('/').includes('..');
  } catch {
    return true;
  }
}

function sendStaticFile(reply: FastifyReply, path: string): FastifyReply {
  const cacheControl = path.startsWith('assets/')
    ? 'public, max-age=31536000, immutable'
    : 'no-cache';
  reply.header('Cache-Control', cacheControl);
  return reply.sendFile(path);
}
