"""用明确标记的模型替身检查真实请求内容，不用替身表现推断领域准确率。"""
import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import asdict
from pathlib import Path
from typing import cast

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
        requests = self.requests
        requests.append(request)
        try:
            for event in self.responses[index]:
                yield event
        finally:
            self.closed_calls += 1


def run_input(message: str='请分析材料', *, model: str='test-model') -> RunInput:
    conversation_command = ConversationCommand('same-session', 'request-1', message)
    run_profile = RunProfile('test-profile', model)
    input_value = RunInput(conversation_command, run_profile)
    return input_value


def activation(call_id: str='activate-1') -> list[ModelEvent]:
    tool_call = ToolCall(call_id, 'activate_skill', '{"name":"analysis-test"}')
    tool_call_ready = ToolCallReady(tool_call)
    model_completed = ModelCompleted('tool_calls')
    return [tool_call_ready, model_completed]


async def test_progressive_disclosure_closed_loop_preserves_visible_text_and_usage(skill_directory: Path) -> None:
    content_delta = ContentDelta('先检查材料。')
    reasoning_delta = ReasoningDelta('公开说明1')
    token_usage = TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    usage_reported = UsageReported(token_usage)
    token_usage_2 = TokenUsage(input_tokens=3, output_tokens=2, reasoning_tokens=1, total_tokens=5)
    usage_reported_2 = UsageReported(token_usage_2)
    activation_2 = activation()
    tool_call = ToolCall('read-1', 'read_skill_resource', '{"name":"analysis-test","relative_path":"references/selected.md"}')
    tool_call_ready = ToolCallReady(tool_call)
    token_usage_3 = TokenUsage(input_tokens=4, output_tokens=3, reasoning_tokens=1, total_tokens=7)
    usage_reported_3 = UsageReported(token_usage_3)
    model_completed = ModelCompleted('tool_calls')
    reasoning_delta_2 = ReasoningDelta('公开说明2')
    content_delta_2 = ContentDelta('根据材料得出结论。')
    token_usage_4 = TokenUsage(input_tokens=5, output_tokens=4, reasoning_tokens=2, total_tokens=9)
    usage_reported_4 = UsageReported(token_usage_4)
    token_usage_5 = TokenUsage()
    usage_reported_5 = UsageReported(token_usage_5)
    model_completed_2 = ModelCompleted('stop')
    responses: list[list[ModelEvent]] = [
        [content_delta, reasoning_delta, usage_reported, usage_reported_2, *activation_2],
        [tool_call_ready, usage_reported_3, model_completed],
        [reasoning_delta_2, content_delta_2, usage_reported_4, usage_reported_5, model_completed_2],
    ]
    model = ScriptedModel(responses)
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    runner = create_agent_runner(model, catalog)
    input_value = run_input()
    stream = runner.stream(input_value)
    events = [event async for event in stream]
    matches_type = isinstance(events[-1], RunFinished)
    assert matches_type
    finished = cast(RunFinished, events[-1])
    result = finished.result
    assert result.reply.content == '先检查材料。根据材料得出结论。'
    assert result.reply.reasoning == '公开说明1公开说明2'
    token_usage_6 = TokenUsage(input_tokens=12, output_tokens=9, reasoning_tokens=4, total_tokens=21)
    assert result.reply.usage == token_usage_6
    assert result.model_calls == 3 and result.tool_executions == 2
    snapshots = []
    for request in model.requests:
        request_data = asdict(request)
        snapshot = repr(request_data)
        snapshots.append(snapshot)
    first, second, third = snapshots
    assert 'analysis-test' in first and 'mechanics-test' in first
    assert 'ANALYSIS_BODY' not in first and 'SELECTED_RESOURCE' not in first
    assert 'ANALYSIS_BODY' in second and 'SELECTED_RESOURCE' not in second
    assert 'SELECTED_RESOURCE' in third and 'UNUSED_RESOURCE' not in third
    all_result = all('MECHANICS_BODY' not in snapshot for snapshot in (first, second, third))
    assert all_result
    tool_messages = [message for message in model.requests[-1].messages if message.role == MessageRole.TOOL]
    assert [message.tool_call_id for message in tool_messages] == ['activate-1', 'read-1']
    assert model.closed_calls == 3


async def test_explicit_skill_activation_precedes_first_call_and_deduplicates(skill_directory: Path) -> None:
    content_delta = ContentDelta('已分析')
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, model_completed]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    input_value = run_input('请使用 $analysis-test 再次指定 $analysis-test')
    result = await generated_runner.run(input_value)
    assert result.activated_skills == ('analysis-test',)
    assert result.tool_executions == 1
    asdict_2 = asdict(model.requests[0])
    snapshot = repr(asdict_2)
    count = snapshot.count('ANALYSIS_BODY')
    assert count == 1
    asdict_3 = asdict(model.requests[0])
    snapshot_2 = repr(asdict_3)
    assert 'SELECTED_RESOURCE' not in snapshot_2


async def test_unknown_explicit_skill_fails_before_model_call(skill_directory: Path) -> None:
    model = ScriptedModel([])
    expected_error = pytest.raises(ExplicitSkillError, match='不在可用目录')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input('使用 $unknown-skill')
        await generated_runner.run(input_value)
    assert model.requests == []


async def test_explicit_activation_obeys_same_disclosure_budget(skill_directory: Path) -> None:
    model = ScriptedModel([])
    expected_error = pytest.raises(BudgetExceeded, match='披露')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input('$analysis-test')
        run_limits = RunLimits(max_disclosure_characters=1)
        await generated_runner.run(input_value, run_limits)
    assert model.requests == []


async def test_next_message_and_model_switch_do_not_retain_skill_bodies(skill_directory: Path) -> None:
    content_delta = ContentDelta('旧轮回答')
    model_completed = ModelCompleted('stop')
    content_delta_2 = ContentDelta('新轮回答')
    model_completed_2 = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, model_completed], [content_delta_2, model_completed_2]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    runner = create_agent_runner(model, catalog)
    first_input = run_input('$analysis-test 帮我分析', model='model-a')
    first = await runner.run(first_input)
    conversation_command = ConversationCommand('same-session', 'request-2', '换个话题')
    run_profile = RunProfile('other', 'model-b')
    conversation_turn = ConversationTurn(first_input.command.message, first.reply)
    second_input = RunInput(conversation_command, run_profile, (conversation_turn,))
    second = await runner.run(second_input)
    asdict_2 = asdict(model.requests[1])
    snapshot = repr(asdict_2)
    assert model.requests[1].model == 'model-b'
    assert '旧轮回答' in snapshot and 'analysis-test' in snapshot
    assert 'ANALYSIS_BODY' not in snapshot
    assert second.activated_skills == ()


@pytest.mark.parametrize('limit,expected', [(1, []), (3, ['user-3']), (4, ['user-2', 'user-3'])])
async def test_history_limit_is_message_count_and_preserves_full_turns(skill_directory: Path, limit: int, expected: list[str]) -> None:
    content_delta = ContentDelta('回答')
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, model_completed]])
    turns = []
    indices = range(1, 4)
    for index in indices:
        reply = AssistantReply(f'assistant-{index}')
        turn = ConversationTurn(f'user-{index}', reply)
        turns.append(turn)
    history = tuple(turns)
    conversation_command = ConversationCommand('s', 'r', '当前消息')
    run_profile = RunProfile('p', 'model', history_limit=limit)
    request = RunInput(conversation_command, run_profile, history)
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    await generated_runner.run(request)
    users = [message.content for message in model.requests[0].messages if message.role == MessageRole.USER]
    assert users == expected + ['当前消息']


async def test_unknown_tool_error_allows_model_to_correct_it(skill_directory: Path) -> None:
    tool_call = ToolCall('a', 'unregistered', '{}')
    tool_call_ready = ToolCallReady(tool_call)
    model_completed = ModelCompleted('tool_calls')
    content_delta = ContentDelta('当前没有该查询能力，请提供材料。')
    model_completed_2 = ModelCompleted('stop')
    model = ScriptedModel([[tool_call_ready, model_completed], [content_delta, model_completed_2]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    input_value = run_input()
    result = await generated_runner.run(input_value)
    assert 'UNKNOWN_TOOL' in model.requests[1].messages[-1].content
    assert result.tool_executions == 1


@pytest.mark.parametrize('responses', [[[ToolCallReady(ToolCall('a', 'echo_text', '{"text":"x"}'))]], [[*activation(), ContentDelta('unexpected-after-completion')]], [[ContentDelta('截断'), ModelCompleted('length')]], [[*activation()], [*activation()]]])
async def test_incomplete_or_repeated_model_protocol_is_rejected(skill_directory: Path, responses: list[list[ModelEvent]]) -> None:
    model = ScriptedModel(responses)
    expected_error = pytest.raises(ModelProtocolError)
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input()
        await generated_runner.run(input_value)


async def test_infinite_tool_requests_stop_at_model_budget(skill_directory: Path) -> None:
    activation_2 = activation('a')
    activation_3 = activation('b')
    activation_4 = activation('c')
    model = ScriptedModel([activation_2, activation_3, activation_4])
    expected_error = pytest.raises(BudgetExceeded, match='模型调用次数')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input()
        run_limits = RunLimits(max_model_calls=2)
        await generated_runner.run(input_value, run_limits)
    item_count = len(model.requests)
    assert item_count == 2


async def test_context_budget_fails_before_model_call(skill_directory: Path) -> None:
    model = ScriptedModel([])
    expected_error = pytest.raises(BudgetExceeded, match='上下文')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input()
        run_limits = RunLimits(max_context_characters=20)
        await generated_runner.run(input_value, run_limits)
    assert model.requests == []


async def test_missing_usage_is_unknown_instead_of_incomplete_sum(skill_directory: Path) -> None:
    token_usage = TokenUsage(input_tokens=5, total_tokens=8)
    usage_reported = UsageReported(token_usage)
    activation_2 = activation()
    content_delta = ContentDelta('回答')
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[usage_reported, *activation_2], [content_delta, model_completed]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    input_value = run_input()
    result = await generated_runner.run(input_value)
    token_usage_2 = TokenUsage()
    assert result.reply.usage == token_usage_2


async def test_closing_consumer_closes_model_stream(skill_directory: Path) -> None:
    content_delta = ContentDelta('partial')
    content_delta_2 = ContentDelta('never-read')
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, content_delta_2, model_completed]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    runner = create_agent_runner(model, catalog)
    input_value = run_input()
    stream = runner.stream(input_value)
    aclosing_2 = aclosing(stream)
    async with aclosing_2 as stream_2:
        anext_result = await anext(stream_2)
        content_delta_3 = ContentDelta('partial')
        assert anext_result == content_delta_3
    assert model.closed_calls == 1


async def test_cancellation_propagates_and_closes_upstream(skill_directory: Path) -> None:
    started = asyncio.Event()
    closed = asyncio.Event()

    class WaitingModel:

        async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelEvent, None]:
            try:
                started.set()
                event = asyncio.Event()
                await event.wait()
                content_delta = ContentDelta('unreachable')
                yield content_delta
            finally:
                closed.set()
    waiting_model = WaitingModel()
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    runner = create_agent_runner(waiting_model, catalog)
    input_value = run_input()
    run = runner.run(input_value)
    task = asyncio.create_task(run)
    wait = started.wait()
    await asyncio.wait_for(wait, timeout=2)
    task.cancel()
    expected_error = pytest.raises(asyncio.CancelledError)
    with expected_error:
        await task
    is_set = closed.is_set()
    assert is_set


async def test_echo_sample_runs_through_same_tool_loop(skill_directory: Path) -> None:
    tool_call = ToolCall('echo', 'echo_text', '{"text":"用户材料"}')
    tool_call_ready = ToolCallReady(tool_call)
    model_completed = ModelCompleted('tool_calls')
    content_delta = ContentDelta('处理成功')
    model_completed_2 = ModelCompleted('stop')
    model = ScriptedModel([[tool_call_ready, model_completed], [content_delta, model_completed_2]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    skills = SkillService(catalog)
    skill_tools = create_skill_tools(skills)
    echo_tool = create_echo_tool()
    tools = ToolRegistry((*skill_tools, echo_tool))
    context_builder = ContextBuilder(skills, tools)
    runner = AgentRunner(model, tools, context_builder)
    input_value = run_input()
    result = await runner.run(input_value)
    assert result.reply.content == '处理成功'
    assert '用户材料' in model.requests[1].messages[-1].content


async def test_multiple_tools_run_in_order_after_complete_call(skill_directory: Path) -> None:
    tool_call = ToolCall('a', 'activate_skill', '{"name":"analysis-test"}')
    tool_call_ready = ToolCallReady(tool_call)
    tool_call_2 = ToolCall('b', 'read_skill_resource', '{"name":"analysis-test","relative_path":"references/selected.md"}')
    tool_call_ready_2 = ToolCallReady(tool_call_2)
    model_completed = ModelCompleted('tool_calls')
    content_delta = ContentDelta('完整分析')
    model_completed_2 = ModelCompleted('stop')
    responses: list[list[ModelEvent]] = [[tool_call_ready, tool_call_ready_2, model_completed], [content_delta, model_completed_2]]
    model = ScriptedModel(responses)
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    input_value = run_input()
    result = await generated_runner.run(input_value)
    assert result.tool_executions == 2
    messages = model.requests[1].messages[-2:]
    assert [message.tool_call_id for message in messages] == ['a', 'b']
    assert '"success":true' in messages[0].content
    assert 'SELECTED_RESOURCE' in messages[1].content


@pytest.mark.parametrize('message', ['价格是 $100', '$analysis-test/../../config.json'])
async def test_currency_and_path_expressions_are_not_partial_skill_names(skill_directory: Path, message: str) -> None:
    content_delta = ContentDelta('正常回答')
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, model_completed]])
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    generated_runner = create_agent_runner(model, catalog)
    input_value = run_input(message)
    result = await generated_runner.run(input_value)
    assert result.activated_skills == ()


async def test_model_output_character_budget_terminates_run(skill_directory: Path) -> None:
    content_delta = ContentDelta('x' * 128001)
    model_completed = ModelCompleted('stop')
    model = ScriptedModel([[content_delta, model_completed]])
    expected_error = pytest.raises(BudgetExceeded, match='输出字符')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input()
        await generated_runner.run(input_value)


async def test_excessive_tool_batch_terminates_before_execution(skill_directory: Path) -> None:
    tool_call = ToolCall('a', 'activate_skill', '{"name":"analysis-test"}')
    tool_call_ready = ToolCallReady(tool_call)
    tool_call_2 = ToolCall('b', 'activate_skill', '{"name":"mechanics-test"}')
    tool_call_ready_2 = ToolCallReady(tool_call_2)
    model_completed = ModelCompleted('tool_calls')
    model = ScriptedModel([[tool_call_ready, tool_call_ready_2, model_completed]])
    expected_error = pytest.raises(BudgetExceeded, match='剩余预算')
    with expected_error:
        catalog = FilesystemSkillCatalog.discover(skill_directory)
        generated_runner = create_agent_runner(model, catalog)
        input_value = run_input()
        run_limits = RunLimits(max_tool_executions=1)
        await generated_runner.run(input_value, run_limits)
    assert model.closed_calls == 1
