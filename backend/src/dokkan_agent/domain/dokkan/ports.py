"""后续数据服务的替换端口；当前没有生产适配器，也不注册伪 Wiki 查询工具。"""

from dataclasses import dataclass
from typing import Protocol

from dokkan_agent.domain.tool.models import JsonValue


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    """候选实体不等于已确认卡片；ID 由真实上游定义，不能从名字臆造。"""

    entity_id: str
    name: str
    summary: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeSelection:
    """只请求当前任务所需字段/章节，避免一次拉取整份 Wiki。"""

    entity_id: str
    fields: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeEvidence:
    """来源和版本允许未知；缺失就省略，不能拼接看似真实的链接。"""

    entity_id: str
    content: JsonValue
    source_id: str | None = None
    source_url: str | None = None
    version: str | None = None


class KnowledgeGateway(Protocol):
    """只定义候选查找和按需读取；实际失败/超时适配在取得上游协议后补充。"""

    async def find_candidates(self, query: str) -> tuple[KnowledgeCandidate, ...]: ...

    async def read_entity(self, selection: KnowledgeSelection) -> KnowledgeEvidence: ...
