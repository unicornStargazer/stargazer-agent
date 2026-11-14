"""Skill 工具只做参数/结果适配；目录安全和本轮去重由既有用例负责。"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.skill.service import SkillService
from dokkan_agent.application.tool.function_tool import ExecutableTool, FunctionTool, ToolParameters

type SkillName = Annotated[str, Field(min_length=1, max_length=64)]


class ActivateSkillParameters(ToolParameters):
    name: SkillName


class ReadResourceParameters(ActivateSkillParameters):
    relative_path: Annotated[str, Field(min_length=1, max_length=512)]


class ResourceInfo(BaseModel):
    relative_path: str
    version: str
    kind: Literal["text", "binary", "script"]


class ActivationOutput(BaseModel):
    name: str
    version: str
    already_active: bool
    instructions: str | None = None
    resources: list[ResourceInfo] | None = None


class ResourceOutput(BaseModel):
    name: str
    relative_path: str
    version: str
    already_loaded: bool
    content: str | None = None


def create_skill_tools(service: SkillService) -> tuple[ExecutableTool, ...]:
    """静态创建两个工具；没有 Skill 声明可以扩充这个集合。"""

    async def activate(parameters: ActivateSkillParameters, context: RunContext) -> ActivationOutput:
        activated = await service.activate(parameters.name, context)
        resources = None
        if not activated.already_active:
            resources = []
            for item in activated.resources:
                resource = ResourceInfo(relative_path=item.relative_path, version=item.version, kind=item.kind)
                resources.append(resource)
        output = ActivationOutput(name=activated.descriptor.name, version=activated.version, already_active=activated.already_active, instructions=None if activated.already_active else activated.instructions, resources=resources)
        return output

    async def read_resource(parameters: ReadResourceParameters, context: RunContext) -> ResourceOutput:
        loaded = await service.read_resource(parameters.name, parameters.relative_path, context)
        output = ResourceOutput(name=loaded.skill_name, relative_path=loaded.resource.relative_path, version=loaded.resource.version, already_loaded=loaded.already_loaded, content=None if loaded.already_loaded else loaded.content)
        return output

    activation_tool = FunctionTool(name="activate_skill", description="按任务激活目录中的 Skill，获取正文和资源清单。", parameters=ActivateSkillParameters, output=ActivationOutput, handler=activate)
    resource_tool = FunctionTool(name="read_skill_resource", description="读取已激活 Skill 清单中的一个 UTF-8 文本资源。", parameters=ReadResourceParameters, output=ResourceOutput, handler=read_resource)
    return activation_tool, resource_tool
