# Tool 扩展

Tool 是由服务端明确授权给模型的一项能力。全局 Skill Catalog 只能告诉模型何时应使用 Tool，不能注册 Tool 或获取文件、网络、命令等权限。

当前项目已注册一个可运行的 `echo_text` 示例，位于 `src/tools/examples/echo-text-tool.ts`。当用户明确要求验证工具调用时，模型可调用它并得到原样返回的文本。

```text
用户 -> 模型请求 echo_text -> ToolRegistry 白名单校验 -> echo_text -> 模型生成最终回复
```

示例 Tool 只接受一个非空 `text` 字段，最大 1000 个字符；它不访问文件、网络、命令和数据库。

默认 Tool 的唯一装配入口是 `src/tools/default-tool-registry.ts`：

```ts
export function createDefaultToolRegistry(): ToolRegistry {
  return new ToolRegistry([echoTextTool]);
}
```

新增业务 Tool 时，实现 `AgentTool`，在此处显式加入注册表，并完成输入校验、超时和错误语义设计。不要根据模型输出动态创建 Tool，也不要让 Tool 接收 HTTP 请求对象、凭据或未校验的文件路径。
