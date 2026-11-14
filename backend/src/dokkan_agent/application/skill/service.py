"""让自动与显式激活走同一用例；文件快照验证由 Catalog 负责。"""

from dataclasses import replace

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.domain.skill.errors import SkillAccessError
from dokkan_agent.domain.skill.models import ActivatedSkill, LoadedSkillResource, SkillDescriptor
from dokkan_agent.domain.skill.ports import SkillCatalog
from dokkan_agent.domain.tool.models import ToolErrorCode


class SkillService:
    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        catalog = self._catalog
        descriptors = catalog.descriptors()
        return descriptors

    async def activate(self, name: str, context: RunContext) -> ActivatedSkill:
        """成功加载后计入激活数；重复调用仍检查部署变化，但不再次披露正文。"""
        catalog = self._catalog
        activated = await catalog.load_skill(name)
        if name in context.activated_skills:
            repeated = replace(activated, instructions="", resources=(), already_active=True)
            return repeated
        budget = context.budget
        budget.consume_activation()
        context.activated_skills[name] = activated
        return activated

    async def read_resource(self, name: str, relative_path: str, context: RunContext) -> LoadedSkillResource:
        """资源必须先激活；重复读也计入读取预算，正文只进入上下文一次。"""
        resource_key = (name, relative_path)
        budget = context.budget
        budget.consume_resource_read()
        if name not in context.activated_skills:
            raise SkillAccessError(ToolErrorCode.SKILL_NOT_ACTIVE, "请先激活对应 Skill，再读取资源。")
        catalog = self._catalog
        loaded = await catalog.read_resource(name, relative_path)
        characters = len(loaded.content)
        if characters > context.budget.limits.max_resource_characters:
            raise SkillAccessError(ToolErrorCode.RESOURCE_TOO_LARGE, "资源超过单次字符上限，请选择清单中更小的文件。")
        if resource_key in context.loaded_resources:
            repeated = replace(loaded, content="", already_loaded=True)
            return repeated
        context.loaded_resources[resource_key] = loaded
        return loaded
