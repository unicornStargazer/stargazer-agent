/**
 * 为 Node 21 提供 Vite 依赖所需的 crypto.hash 等价实现。
 *
 * Node 22 已原生提供该 API，因此不覆盖原生实现；此文件只服务构建工具，不会进入浏览器产物。
 */

import crypto from 'node:crypto';
import type { BinaryLike, BinaryToTextEncoding } from 'node:crypto';

if (typeof crypto.hash !== 'function') {
  Object.assign(crypto, {
    hash(algorithm: string, data: BinaryLike, outputEncoding?: BinaryToTextEncoding) {
      const hash = crypto.createHash(algorithm).update(data);
      return outputEncoding === undefined ? hash.digest() : hash.digest(outputEncoding);
    },
  });
}
