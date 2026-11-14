"""Agent 内核装配：向领域端口注入实际实现；不会主动发送模型请求。"""

from dokkan_agent.application.runtime.context_builder import ContextBuilder
from dokkan_agent.application.runtime.runner import AgentRunner
from dokkan_agent.application.skill.service import SkillService
from dokkan_agent.application.tool.registry import ToolRegistry
from dokkan_agent.bootstrap.settings import RuntimeSettings
from dokkan_agent.domain.agent.budget import RunLimits
from dokkan_agent.domain.agent.ports import ModelGateway
from dokkan_agent.domain.skill.ports import SkillCatalog
from dokkan_agent.infrastructure.tool.skill_tools import create_skill_tools


def create_agent_runner(model: ModelGateway, catalog: SkillCatalog) -> AgentRunner:
    """正式集合只注册 Skill 工具；echo 示例由演示/测试单独装配。"""
    skills = SkillService(catalog)
    skill_tools = create_skill_tools(skills)
    tools = ToolRegistry(skill_tools)
    builder = ContextBuilder(skills, tools)
    runner = AgentRunner(model, tools, builder)
    return runner


def create_run_limits(settings: RuntimeSettings) -> RunLimits:
    """配置 DTO 到纯领域对象的显式边界，不让运行器依赖 Pydantic 配置。"""
    values = settings.model_dump()
    limits = RunLimits(**values)
    return limits
