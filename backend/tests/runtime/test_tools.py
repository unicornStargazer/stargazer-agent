"""静态注册、输入/输出校验、按需披露和各类工具预算的可观测行为。"""

from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.skill.service import SkillService
from dokkan_agent.application.tool.function_tool import FunctionTool, ToolParameters
from dokkan_agent.application.tool.registry import ToolRegistry, serialize_tool_result
from dokkan_agent.domain.agent.budget import BudgetExceeded, RunBudget, RunLimits
from dokkan_agent.domain.tool.models import ToolCall, ToolErrorCode
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog
from dokkan_agent.infrastructure.tool.echo_tool import create_echo_tool
from dokkan_agent.infrastructure.tool.skill_tools import create_skill_tools


@pytest.fixture
def tools(skill_directory: Path) -> ToolRegistry:
    return ToolRegistry(
        (
            *create_skill_tools(SkillService(FilesystemSkillCatalog.discover(skill_directory))),
            create_echo_tool(),
        )
    )


@pytest.mark.parametrize(
    "arguments",
    [
        "not json",
        '"string"',
        "[]",
        '{"text":1}',
        '{"text":"a","text":"b"}',
        '{"text":"a","extra":true}',
        '{"text":NaN}',
        '{"text":""}',
    ],
)
async def test_invalid_tool_arguments_are_safe_and_counted(
    tools: ToolRegistry, arguments: str
) -> None:
    context = RunContext(RunBudget(RunLimits()))
    result = await tools.execute(ToolCall("id1", "echo_text", arguments), context)
    assert result.error and result.error.code == ToolErrorCode.INVALID_ARGUMENTS
    assert context.budget.tool_executions == 1


async def test_only_registered_tools_execute(tools: ToolRegistry) -> None:
    context = RunContext(RunBudget(RunLimits()))
    result = await tools.execute(ToolCall("id1", "Bash", "{}"), context)
    assert result.error and result.error.code == ToolErrorCode.UNKNOWN_TOOL
    result = await tools.execute(ToolCall("id2", "echo_text", '{"text":"你好"}'), context)
    assert result.payload == {"text": "你好"}


async def test_activation_and_resource_deduplication(tools: ToolRegistry) -> None:
    context = RunContext(RunBudget(RunLimits()))
    activate = ToolCall("a", "activate_skill", '{"name":"analysis-test"}')
    read = ToolCall(
        "b",
        "read_skill_resource",
        '{"name":"analysis-test","relative_path":"references/selected.md"}',
    )
    not_active = await tools.execute(read, context)
    assert not_active.error and not_active.error.code == ToolErrorCode.SKILL_NOT_ACTIVE
    assert "ANALYSIS_BODY" in serialize_tool_result(await tools.execute(activate, context))
    repeated = serialize_tool_result(await tools.execute(activate, context))
    assert '"already_active":true' in repeated and "ANALYSIS_BODY" not in repeated
    assert "SELECTED_RESOURCE" in serialize_tool_result(await tools.execute(read, context))
    repeated_resource = serialize_tool_result(await tools.execute(read, context))
    assert (
        '"already_loaded":true' in repeated_resource
        and "SELECTED_RESOURCE" not in repeated_resource
    )
    assert context.budget.activated_skills == 1
    assert context.budget.resource_reads == 3


async def test_resource_limit_returns_error_without_partial_content(skill_directory: Path) -> None:
    path = skill_directory / "analysis-test/references/selected.md"
    path.write_text("secret-long-resource" * 100, encoding="utf-8")
    registry = ToolRegistry(
        create_skill_tools(SkillService(FilesystemSkillCatalog.discover(skill_directory)))
    )
    context = RunContext(RunBudget(RunLimits(max_resource_characters=10)))
    await registry.execute(ToolCall("a", "activate_skill", '{"name":"analysis-test"}'), context)
    result = await registry.execute(
        ToolCall(
            "b",
            "read_skill_resource",
            '{"name":"analysis-test","relative_path":"references/selected.md"}',
        ),
        context,
    )
    assert result.error and result.error.code == ToolErrorCode.RESOURCE_TOO_LARGE
    assert "secret-long-resource" not in serialize_tool_result(result)
    assert context.loaded_resources == {}


@pytest.mark.parametrize("budget", ["tools", "disclosure", "activations", "reads"])
async def test_hard_budgets_abort_instead_of_becoming_recoverable_errors(
    tools: ToolRegistry, budget: str
) -> None:
    limits = RunLimits(max_tool_executions=1) if budget == "tools" else RunLimits()
    if budget == "disclosure":
        limits = RunLimits(max_disclosure_characters=1)
    elif budget == "activations":
        limits = RunLimits(max_activated_skills=1)
    elif budget == "reads":
        limits = RunLimits(max_resource_reads=1)
    context = RunContext(RunBudget(limits))
    first = ToolCall("a", "activate_skill", '{"name":"analysis-test"}')
    if budget == "disclosure":
        with pytest.raises(BudgetExceeded):
            await tools.execute(first, context)
        return
    await tools.execute(first, context)
    second = ToolCall("b", "activate_skill", '{"name":"mechanics-test"}')
    if budget == "reads":
        second = ToolCall(
            "b",
            "read_skill_resource",
            '{"name":"analysis-test","relative_path":"references/selected.md"}',
        )
        await tools.execute(second, context)
    with pytest.raises(BudgetExceeded):
        await tools.execute(second, context)


@pytest.mark.parametrize("invalid_instance", [False, True])
async def test_broken_tool_output_is_not_reported_as_invalid_user_arguments(
    invalid_instance: bool,
) -> None:
    class Parameters(ToolParameters):
        text: str

    class Output(BaseModel):
        text: str

    async def broken(parameters: Parameters, context: RunContext) -> Output:
        if invalid_instance:
            return Output.model_construct(text=123)
        return cast(Output, {"text": 123})

    tool = FunctionTool(
        name="broken",
        description="仅用于测试错误输出",
        parameters=Parameters,
        output=Output,
        handler=broken,
    )
    result = await ToolRegistry([tool]).execute(
        ToolCall("a", "broken", '{"text":"valid"}'), RunContext(RunBudget(RunLimits()))
    )
    assert result.error and result.error.code == ToolErrorCode.EXECUTION_FAILED
