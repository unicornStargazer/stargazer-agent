"""用明确标记的模型替身检查真实请求内容，不用替身表现推断领域准确率。"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import asdict
from pathlib import Path

import pytest

from dokkan_agent.application.runtime.context_builder import ContextBuilder
from dokkan_agent.application.runtime.models import (
    ExplicitSkillError,
    ModelProtocolError,
    RunFinished,
    RunInput,
    RunProfile,
)
from dokkan_agent.application.runtime.runner import AgentRunner
from dokkan_agent.application.skill.service import SkillService
from dokkan_agent.application.tool.registry import ToolRegistry
from dokkan_agent.bootstrap.runtime import create_agent_runner
from dokkan_agent.domain.agent.budget import BudgetExceeded, RunLimits
from dokkan_agent.domain.agent.models import (
    ContentDelta,
    MessageRole,
    ModelCompleted,
    ModelEvent,
    ModelRequest,
    ReasoningDelta,
    TokenUsage,
    ToolCallReady,
    UsageReported,
)
from dokkan_agent.domain.conversation.models import (
    AssistantReply,
    ConversationCommand,
    ConversationTurn,
)
from dokkan_agent.domain.tool.models import ToolCall
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog
from dokkan_agent.infrastructure.tool.echo_tool import create_echo_tool
from dokkan_agent.infrastructure.tool.skill_tools import create_skill_tools


class ScriptedModel:
    """只回放测试脚本，不执行真实推理；记录实际模型输入供披露断言。"""

    def __init__(self, responses: list[list[ModelEvent]]) -> None:
        self.responses = responses
        self.requests: list[ModelRequest] = []
        self.closed_calls = 0

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
        index = len(self.requests)
        self.requests.append(request)
        try:
            for event in self.responses[index]:
                yield event
        finally:
            self.closed_calls += 1


def run_input(message: str = "请分析材料", *, model: str = "test-model") -> RunInput:
    return RunInput(
        ConversationCommand("same-session", "request-1", message), RunProfile("test-profile", model)
    )


def activation(call_id: str = "activate-1") -> list[ModelEvent]:
    return [
        ToolCallReady(ToolCall(call_id, "activate_skill", '{"name":"analysis-test"}')),
        ModelCompleted("tool_calls"),
    ]


async def test_progressive_disclosure_closed_loop_preserves_visible_text_and_usage(
    skill_directory: Path,
) -> None:
    model = ScriptedModel(
        [
            [
                ContentDelta("先检查材料。"),
                ReasoningDelta("公开说明1"),
                UsageReported(TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2)),
                UsageReported(
                    TokenUsage(input_tokens=3, output_tokens=2, reasoning_tokens=1, total_tokens=5)
                ),
                *activation(),
            ],
            [
                ToolCallReady(
                    ToolCall(
                        "read-1",
                        "read_skill_resource",
                        '{"name":"analysis-test","relative_path":"references/selected.md"}',
                    )
                ),
                UsageReported(
                    TokenUsage(input_tokens=4, output_tokens=3, reasoning_tokens=1, total_tokens=7)
                ),
                ModelCompleted("tool_calls"),
            ],
            [
                ReasoningDelta("公开说明2"),
                ContentDelta("根据材料得出结论。"),
                UsageReported(
                    TokenUsage(input_tokens=5, output_tokens=4, reasoning_tokens=2, total_tokens=9)
                ),
                UsageReported(TokenUsage()),
                ModelCompleted("stop"),
            ],
        ]
    )
    runner = create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory))
    events = [event async for event in runner.stream(run_input())]
    assert isinstance(events[-1], RunFinished)
    result = events[-1].result
    assert result.reply.content == "先检查材料。根据材料得出结论。"
    assert result.reply.reasoning == "公开说明1公开说明2"
    assert result.reply.usage == TokenUsage(
        input_tokens=12, output_tokens=9, reasoning_tokens=4, total_tokens=21
    )
    assert result.model_calls == 3 and result.tool_executions == 2
    first, second, third = [repr(asdict(request)) for request in model.requests]
    assert "analysis-test" in first and "mechanics-test" in first
    assert "ANALYSIS_BODY" not in first and "SELECTED_RESOURCE" not in first
    assert "ANALYSIS_BODY" in second and "SELECTED_RESOURCE" not in second
    assert "SELECTED_RESOURCE" in third and "UNUSED_RESOURCE" not in third
    assert all("MECHANICS_BODY" not in snapshot for snapshot in (first, second, third))
    tool_messages = [
        message for message in model.requests[-1].messages if message.role == MessageRole.TOOL
    ]
    assert [message.tool_call_id for message in tool_messages] == ["activate-1", "read-1"]
    assert model.closed_calls == 3


async def test_explicit_skill_activation_precedes_first_call_and_deduplicates(
    skill_directory: Path,
) -> None:
    model = ScriptedModel([[ContentDelta("已分析"), ModelCompleted("stop")]])
    result = await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
        run_input("请使用 $analysis-test 再次指定 $analysis-test")
    )
    assert result.activated_skills == ("analysis-test",)
    assert result.tool_executions == 1
    assert repr(asdict(model.requests[0])).count("ANALYSIS_BODY") == 1
    assert "SELECTED_RESOURCE" not in repr(asdict(model.requests[0]))


async def test_unknown_explicit_skill_fails_before_model_call(skill_directory: Path) -> None:
    model = ScriptedModel([])
    with pytest.raises(ExplicitSkillError, match="不在可用目录"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input("使用 $unknown-skill")
        )
    assert model.requests == []


async def test_explicit_activation_obeys_same_disclosure_budget(skill_directory: Path) -> None:
    model = ScriptedModel([])
    with pytest.raises(BudgetExceeded, match="披露"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input("$analysis-test"), RunLimits(max_disclosure_characters=1)
        )
    assert model.requests == []


async def test_next_message_and_model_switch_do_not_retain_skill_bodies(
    skill_directory: Path,
) -> None:
    model = ScriptedModel(
        [
            [ContentDelta("旧轮回答"), ModelCompleted("stop")],
            [ContentDelta("新轮回答"), ModelCompleted("stop")],
        ]
    )
    runner = create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory))
    first_input = run_input("$analysis-test 帮我分析", model="model-a")
    first = await runner.run(first_input)
    second_input = RunInput(
        ConversationCommand("same-session", "request-2", "换个话题"),
        RunProfile("other", "model-b"),
        (ConversationTurn(first_input.command.message, first.reply),),
    )
    second = await runner.run(second_input)
    snapshot = repr(asdict(model.requests[1]))
    assert model.requests[1].model == "model-b"
    assert "旧轮回答" in snapshot and "analysis-test" in snapshot
    assert "ANALYSIS_BODY" not in snapshot
    assert second.activated_skills == ()


@pytest.mark.parametrize("limit,expected", [(1, []), (3, ["user-3"]), (4, ["user-2", "user-3"])])
async def test_history_limit_is_message_count_and_preserves_full_turns(
    skill_directory: Path, limit: int, expected: list[str]
) -> None:
    model = ScriptedModel([[ContentDelta("回答"), ModelCompleted("stop")]])
    request = RunInput(
        ConversationCommand("s", "r", "当前消息"),
        RunProfile("p", "model", history_limit=limit),
        tuple(
            ConversationTurn(f"user-{index}", AssistantReply(f"assistant-{index}"))
            for index in range(1, 4)
        ),
    )
    await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(request)
    users = [
        message.content
        for message in model.requests[0].messages
        if message.role == MessageRole.USER
    ]
    assert users == expected + ["当前消息"]


async def test_unknown_tool_error_allows_model_to_correct_it(skill_directory: Path) -> None:
    model = ScriptedModel(
        [
            [ToolCallReady(ToolCall("a", "unregistered", "{}")), ModelCompleted("tool_calls")],
            [ContentDelta("当前没有该查询能力，请提供材料。"), ModelCompleted("stop")],
        ]
    )
    result = await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
        run_input()
    )
    assert "UNKNOWN_TOOL" in model.requests[1].messages[-1].content
    assert result.tool_executions == 1


@pytest.mark.parametrize(
    "responses",
    [
        [[ToolCallReady(ToolCall("a", "echo_text", '{"text":"x"}'))]],
        [[*activation(), ContentDelta("unexpected-after-completion")]],
        [[ContentDelta("截断"), ModelCompleted("length")]],
        [[*activation()], [*activation()]],
    ],
)
async def test_incomplete_or_repeated_model_protocol_is_rejected(
    skill_directory: Path, responses: list[list[ModelEvent]]
) -> None:
    model = ScriptedModel(responses)
    with pytest.raises(ModelProtocolError):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input()
        )


async def test_infinite_tool_requests_stop_at_model_budget(skill_directory: Path) -> None:
    model = ScriptedModel([activation("a"), activation("b"), activation("c")])
    with pytest.raises(BudgetExceeded, match="模型调用次数"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input(), RunLimits(max_model_calls=2)
        )
    assert len(model.requests) == 2


async def test_context_budget_fails_before_model_call(skill_directory: Path) -> None:
    model = ScriptedModel([])
    with pytest.raises(BudgetExceeded, match="上下文"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input(), RunLimits(max_context_characters=20)
        )
    assert model.requests == []


async def test_missing_usage_is_unknown_instead_of_incomplete_sum(skill_directory: Path) -> None:
    model = ScriptedModel(
        [
            [UsageReported(TokenUsage(input_tokens=5, total_tokens=8)), *activation()],
            [ContentDelta("回答"), ModelCompleted("stop")],
        ]
    )
    result = await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
        run_input()
    )
    assert result.reply.usage == TokenUsage()


async def test_closing_consumer_closes_model_stream(skill_directory: Path) -> None:
    model = ScriptedModel(
        [[ContentDelta("partial"), ContentDelta("never-read"), ModelCompleted("stop")]]
    )
    runner = create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory))
    async with aclosing(runner.stream(run_input())) as stream:
        assert await anext(stream) == ContentDelta("partial")
    assert model.closed_calls == 1


async def test_cancellation_propagates_and_closes_upstream(skill_directory: Path) -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    class WaitingModel:
        async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
            try:
                started.set()
                await asyncio.Event().wait()
                yield ContentDelta("unreachable")
            finally:
                closed.set()

    runner = create_agent_runner(WaitingModel(), FilesystemSkillCatalog.discover(skill_directory))
    task = asyncio.create_task(runner.run(run_input()))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_echo_sample_runs_through_same_tool_loop(skill_directory: Path) -> None:
    model = ScriptedModel(
        [
            [
                ToolCallReady(ToolCall("echo", "echo_text", '{"text":"用户材料"}')),
                ModelCompleted("tool_calls"),
            ],
            [ContentDelta("处理成功"), ModelCompleted("stop")],
        ]
    )
    skills = SkillService(FilesystemSkillCatalog.discover(skill_directory))
    tools = ToolRegistry((*create_skill_tools(skills), create_echo_tool()))
    runner = AgentRunner(model, tools, ContextBuilder(skills, tools))
    result = await runner.run(run_input())
    assert result.reply.content == "处理成功"
    assert "用户材料" in model.requests[1].messages[-1].content


async def test_multiple_tools_run_in_order_after_complete_call(skill_directory: Path) -> None:
    model = ScriptedModel(
        [
            [
                ToolCallReady(ToolCall("a", "activate_skill", '{"name":"analysis-test"}')),
                ToolCallReady(
                    ToolCall(
                        "b",
                        "read_skill_resource",
                        '{"name":"analysis-test","relative_path":"references/selected.md"}',
                    )
                ),
                ModelCompleted("tool_calls"),
            ],
            [ContentDelta("完整分析"), ModelCompleted("stop")],
        ]
    )
    result = await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
        run_input()
    )
    assert result.tool_executions == 2
    messages = model.requests[1].messages[-2:]
    assert [message.tool_call_id for message in messages] == ["a", "b"]
    assert '"success":true' in messages[0].content
    assert "SELECTED_RESOURCE" in messages[1].content


@pytest.mark.parametrize("message", ["价格是 $100", "$analysis-test/../../config.json"])
async def test_currency_and_path_expressions_are_not_partial_skill_names(
    skill_directory: Path, message: str
) -> None:
    model = ScriptedModel([[ContentDelta("正常回答"), ModelCompleted("stop")]])
    result = await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
        run_input(message)
    )
    assert result.activated_skills == ()


async def test_model_output_character_budget_terminates_run(skill_directory: Path) -> None:
    model = ScriptedModel([[ContentDelta("x" * 128_001), ModelCompleted("stop")]])
    with pytest.raises(BudgetExceeded, match="输出字符"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input()
        )


async def test_excessive_tool_batch_terminates_before_execution(skill_directory: Path) -> None:
    model = ScriptedModel(
        [
            [
                ToolCallReady(ToolCall("a", "activate_skill", '{"name":"analysis-test"}')),
                ToolCallReady(ToolCall("b", "activate_skill", '{"name":"mechanics-test"}')),
                ModelCompleted("tool_calls"),
            ]
        ]
    )
    with pytest.raises(BudgetExceeded, match="剩余预算"):
        await create_agent_runner(model, FilesystemSkillCatalog.discover(skill_directory)).run(
            run_input(), RunLimits(max_tool_executions=1)
        )
    assert model.closed_calls == 1
