"""标准 Skill 元数据解析；拒绝重复键、对象构造标签和 YAML 别名扩张。"""

from dataclasses import dataclass

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from dokkan_agent.domain.skill.errors import SkillConfigurationError
from dokkan_agent.domain.skill.models import SkillDescriptor, SkillMetadata

MAX_FRONTMATTER_CHARACTERS = 16_384
STANDARD_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


class UniqueKeyLoader(yaml.SafeLoader):
    """只改变映射构造规则，其余沿用 SafeLoader 的安全标量语义。"""


def _construct_mapping(loader: yaml.SafeLoader, node: MappingNode) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise SkillConfigurationError("YAML 字段必须为字符串且不能重复")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True, slots=True)
class ParsedSkill:
    descriptor: SkillDescriptor
    metadata: SkillMetadata
    instructions: str


def parse_skill_document(content: str, directory_name: str) -> ParsedSkill:
    """解析一个完整 UTF-8 文档；只返回合法元数据，不猜测旧格式缺失的描述。"""
    lines = content.lstrip("\ufeff").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillConfigurationError("SKILL.md 必须以 YAML front matter 开始")
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        raise SkillConfigurationError("YAML front matter 缺少结束分隔符")
    header = "".join(lines[1:closing])
    if len(header) > MAX_FRONTMATTER_CHARACTERS:
        raise SkillConfigurationError("YAML front matter 过大")
    fields = _load_fields(header)
    descriptor = _parse_descriptor(fields, directory_name)
    metadata = _parse_metadata(fields)
    return ParsedSkill(descriptor, metadata, "".join(lines[closing + 1 :]).strip())


def _load_fields(header: str) -> dict[str, object]:
    try:
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(header)):
            raise SkillConfigurationError("YAML 不支持锚点和别名，请直接填写字段")
        fields: object = yaml.load(header, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, RecursionError):
        raise SkillConfigurationError("YAML 格式或字段类型无效") from None
    if not isinstance(fields, dict) or any(not isinstance(key, str) for key in fields):
        raise SkillConfigurationError("YAML front matter 必须为字段映射")
    if set(fields) - STANDARD_FIELDS:
        raise SkillConfigurationError("存在非标准字段，请将扩展信息放入 metadata")
    return fields


def _required_text(fields: dict[str, object], key: str, maximum: int | None = None) -> str:
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillConfigurationError(f"{key} 必须是非空字符串")
    if maximum is not None and len(value) > maximum:
        raise SkillConfigurationError(f"{key} 超出长度限制")
    return value


def _parse_descriptor(fields: dict[str, object], directory_name: str) -> SkillDescriptor:
    name = _required_text(fields, "name", 64)
    valid_characters = all(character.isalnum() or character == "-" for character in name)
    invalid_hyphens = name.startswith("-") or name.endswith("-") or "--" in name
    if not valid_characters or invalid_hyphens or name != name.lower():
        raise SkillConfigurationError(
            "name 仅支持小写字母、数字、单个连字符，且不能以连字符开头或结尾"
        )
    if name != directory_name:
        raise SkillConfigurationError("name 必须与 Skill 目录名完全一致")
    return SkillDescriptor(name, _required_text(fields, "description", 1024).strip())


def _parse_metadata(fields: dict[str, object]) -> SkillMetadata:
    optional: dict[str, str | None] = {}
    for key in ("license", "compatibility", "allowed-tools"):
        maximum = 500 if key == "compatibility" else None
        optional[key] = _required_text(fields, key, maximum) if key in fields else None
    metadata = fields.get("metadata", {})
    if not isinstance(metadata, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()
    ):
        raise SkillConfigurationError("metadata 必须是字符串到字符串的映射")
    notices = ("allowed-tools 仅保留元数据，当前不支持其执行语义；能力由服务端静态注册。",)
    return SkillMetadata(
        license=optional["license"],
        compatibility=optional["compatibility"],
        metadata=tuple(sorted(metadata.items())),
        allowed_tools=optional["allowed-tools"],
        notices=notices if "allowed-tools" in fields else (),
    )
