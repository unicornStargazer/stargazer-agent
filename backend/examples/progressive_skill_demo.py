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

EXAMPLE_PATH = Path(__file__)
RESOLVED_EXAMPLE_PATH = EXAMPLE_PATH.resolve()
SKILLS_DIRECTORY = RESOLVED_EXAMPLE_PATH.parent / 'skills'


class ScriptedDemoModel:
    """按预设顺序请求工具；这不是模型自动选择 Skill 的准确率测试。"""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        requests = self.requests
        requests.append(request)
        item_count = len(self.requests)
        match item_count:
            case 1:
                tool_call = ToolCall('activate-demo', 'activate_skill', '{"name":"material-analysis-demo"}')
                tool_call_ready = ToolCallReady(tool_call)
                yield tool_call_ready
                model_completed = ModelCompleted('tool_calls')
                yield model_completed
            case 2:
                tool_call_2 = ToolCall('read-demo', 'read_skill_resource', '{"name":"material-analysis-demo","relative_path":"references/response-checklist.md"}')
                tool_call_ready_2 = ToolCallReady(tool_call_2)
                yield tool_call_ready_2
                model_completed_2 = ModelCompleted('tool_calls')
                yield model_completed_2
            case _:
                content_delta = ContentDelta('演示完成：已按需加载分析指令和一份检查单；回答将以用户材料为依据。')
                yield content_delta
                model_completed_3 = ModelCompleted('stop')
                yield model_completed_3


async def main() -> None:
    catalog = await asyncio.to_thread(FilesystemSkillCatalog.discover, SKILLS_DIRECTORY)
    model = ScriptedDemoModel()
    runner = create_agent_runner(model, catalog)
    conversation_command = ConversationCommand('demo-session', 'demo-request', '请分析我提供的文本材料。')
    run_profile = RunProfile('demo-profile', 'scripted-demo-model')
    input_value = RunInput(conversation_command, run_profile)
    result = await runner.run(input_value)
    print('确定性演示，不调用真实大模型或数据服务。')
    indexed_requests = enumerate(model.requests, start=1)
    newline = '\n'
    for index, request in indexed_requests:
        message_contents = [message.content for message in request.messages]
        text = newline.join(message_contents)
        print(f'请求 {index}: 指令已披露={'先确认用户提供' in text}, 检查单已披露={'标明依据是用户提供' in text}, 未使用资料已披露={'四列' in text}')
    print(result.reply.content)
    print(f'模型调用={result.model_calls}, 工具执行={result.tool_executions}')


if __name__ == '__main__':
    demo = main()
    asyncio.run(demo)
