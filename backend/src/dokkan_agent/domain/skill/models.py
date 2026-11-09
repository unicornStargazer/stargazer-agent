"""将可发现的描述与按需加载的指令、资源分开，防止全量正文常驻。"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """L1 公开目录项；只有名称、描述可以进入初始模型上下文。"""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class SkillResource:
    """可读取的注册文本资源；relative_path 相对该 Skill 根，version 为内容摘要。"""

    relative_path: str
    version: str
    kind: Literal["text", "binary", "script"] = "text"


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    """部署元数据不进入 L1；allowed_tools 仅保留，不控制实际工具注册。"""

    license: str | None = None
    compatibility: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    allowed_tools: str | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActivatedSkill:
    """L2 本轮激活快照；资源清单不含 L3 正文，不跨用户消息永久注入。"""

    descriptor: SkillDescriptor
    instructions: str
    version: str
    resources: tuple[SkillResource, ...]
    already_active: bool = False


@dataclass(frozen=True, slots=True)
class LoadedSkillResource:
    """L3 单个文本快照；已加载标志用于本轮去重，读取仍计入工具预算。"""

    skill_name: str
    resource: SkillResource
    content: str
    already_loaded: bool = False
