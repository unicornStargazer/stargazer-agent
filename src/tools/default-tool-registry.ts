/** 服务端允许模型使用的默认 Tool 白名单。 */
import { echoTextTool } from './examples/echo-text-tool.js';
import { ToolRegistry } from './tool-registry.js';

export function createDefaultToolRegistry(): ToolRegistry {
  return new ToolRegistry([echoTextTool]);
}
