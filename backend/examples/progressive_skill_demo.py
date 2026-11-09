"""确定性内核演示：不连接真实模型/数据库，不能用于评价模型能力或游戏事实。"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from dokkan_agent.application.runtime.models import RunInput, RunProfile
from dokkan_agent.bootstrap.runtime import create_agent_runner
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ToolCallReady,
)
from dokkan_agent.domain.conversation.models import ConversationCommand
from dokkan_agent.domain.tool.models import ToolCall
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog

SKILLS_DIRECTORY = Path(__file__).resolve().parent / "skills"


class ScriptedDemoModel:
    """按预设顺序请求工具；这不是模型自动选择 Skill 的准确率测试。"""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        self.requests.append(request)
        match len(self.requests):
            case 1:
                yield ToolCallReady(
                    ToolCall("activate-demo", "activate_skill", '{"name":"material-analysis-demo"}')
                )
                yield ModelCompleted("tool_calls")
            case 2:
                yield ToolCallReady(
                    ToolCall(
                        "read-demo",
                        "read_skill_resource",
                        '{"name":"material-analysis-demo","relative_path":"references/response-checklist.md"}',
                    )
                )
                yield ModelCompleted("tool_calls")
            case _:
                yield ContentDelta(
                    "演示完成：已按需加载分析指令和一份检查单；回答将以用户材料为依据。"
                )
                yield ModelCompleted("stop")


async def main() -> None:
    catalog = await asyncio.to_thread(FilesystemSkillCatalog.discover, SKILLS_DIRECTORY)
    model = ScriptedDemoModel()
    runner = create_agent_runner(model, catalog)
    result = await runner.run(
        RunInput(
            ConversationCommand("demo-session", "demo-request", "请分析我提供的文本材料。"),
            RunProfile("demo-profile", "scripted-demo-model"),
        )
    )
    print("确定性演示，不调用真实大模型或数据服务。")
    for index, request in enumerate(model.requests, start=1):
        text = "\n".join(message.content for message in request.messages)
        print(
            f"请求 {index}: 指令已披露={'先确认用户提供' in text}, "
            f"检查单已披露={'标明依据是用户提供' in text}, "
            f"未使用资料已披露={'四列' in text}"
        )
    print(result.reply.content)
    print(f"模型调用={result.model_calls}, 工具执行={result.tool_executions}")


if __name__ == "__main__":
    asyncio.run(main())
