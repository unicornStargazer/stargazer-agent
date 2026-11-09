"""每次运行独立的暂存状态；禁止把 Skill 正文或工具结果放入跨轮缓存。"""

from dataclasses import dataclass, field

from dokkan_agent.domain.agent.budget import RunBudget
from dokkan_agent.domain.skill.models import ActivatedSkill, LoadedSkillResource


@dataclass(slots=True)
class RunContext:
    """由 Runner 每轮创建；仅共享不可变目录，激活、资源和预算属于当前请求。"""

    budget: RunBudget
    activated_skills: dict[str, ActivatedSkill] = field(default_factory=dict)
    loaded_resources: dict[tuple[str, str], LoadedSkillResource] = field(default_factory=dict)
