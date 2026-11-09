"""文件目录的替换边界；不把绝对路径或文件句柄传到应用层。"""

from typing import Protocol

from dokkan_agent.domain.skill.models import ActivatedSkill, LoadedSkillResource, SkillDescriptor


class SkillCatalog(Protocol):
    """发现结果在进程内冻结；加载失败抛 SkillAccessError，且不返回部分正文。"""

    def descriptors(self) -> tuple[SkillDescriptor, ...]: ...

    async def load_skill(self, name: str) -> ActivatedSkill: ...

    async def read_resource(self, name: str, relative_path: str) -> LoadedSkillResource: ...
