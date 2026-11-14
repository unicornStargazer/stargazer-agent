"""标准 Skill 元数据解析；拒绝重复键、对象构造标签和 YAML 别名扩张。"""

from dataclasses import dataclass
from typing import cast

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
        is_text = isinstance(key, str)
        if not is_text or key in result:
            raise SkillConfigurationError("YAML 字段必须为字符串且不能重复")
        value = loader.construct_object(value_node, deep=True)
        result[key] = value
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True, slots=True)
class ParsedSkill:
    descriptor: SkillDescriptor
    metadata: SkillMetadata
    instructions: str


def parse_skill_document(content: str, directory_name: str) -> ParsedSkill:
    """解析一个完整 UTF-8 文档；只返回合法元数据，不猜测旧格式缺失的描述。"""
    stripped_content = content.lstrip("﻿")
    lines = stripped_content.splitlines(keepends=True)
    if not lines:
        raise SkillConfigurationError("SKILL.md 必须以 YAML front matter 开始")
    opening = lines[0].strip()
    if opening != "---":
        raise SkillConfigurationError("SKILL.md 必须以 YAML front matter 开始")
    closing = None
    line_count = len(lines)
    indexes = range(1, line_count)
    for index in indexes:
        line = lines[index].strip()
        if line == "---":
            closing = index
            break
    if closing is None:
        raise SkillConfigurationError("YAML front matter 缺少结束分隔符")
    header = "".join(lines[1:closing])
    header_length = len(header)
    if header_length > MAX_FRONTMATTER_CHARACTERS:
        raise SkillConfigurationError("YAML front matter 过大")
    fields = _load_fields(header)
    descriptor = _parse_descriptor(fields, directory_name)
    metadata = _parse_metadata(fields)
    body = "".join(lines[closing + 1:])
    instructions = body.strip()
    parsed = ParsedSkill(descriptor, metadata, instructions)
    return parsed


def _load_fields(header: str) -> dict[str, object]:
    try:
        tokens = yaml.scan(header)
        for token in tokens:
            is_alias = isinstance(token, (AliasToken, AnchorToken))
            if is_alias:
                raise SkillConfigurationError("YAML 不支持锚点和别名，请直接填写字段")
        fields: object = yaml.load(header, Loader=UniqueKeyLoader)
    except (yaml.YAMLError, RecursionError):
        raise SkillConfigurationError("YAML 格式或字段类型无效") from None
    is_mapping = isinstance(fields, dict)
    if not is_mapping:
        raise SkillConfigurationError("YAML front matter 必须为字段映射")
    fields = cast(dict[str, object], fields)
    for key in fields:
        is_text = isinstance(key, str)
        if not is_text:
            raise SkillConfigurationError("YAML front matter 必须为字段映射")
    field_names = set(fields)
    if field_names - STANDARD_FIELDS:
        raise SkillConfigurationError("存在非标准字段，请将扩展信息放入 metadata")
    return fields


def _required_text(fields: dict[str, object], key: str, maximum: int | None = None) -> str:
    value = fields.get(key)
    is_text = isinstance(value, str)
    if not is_text:
        raise SkillConfigurationError(f"{key} 必须是非空字符串")
    value = cast(str, value)
    stripped = value.strip()
    if not stripped:
        raise SkillConfigurationError(f"{key} 必须是非空字符串")
    if maximum is not None:
        length = len(value)
        if length > maximum:
            raise SkillConfigurationError(f"{key} 超出长度限制")
    return value


def _parse_descriptor(fields: dict[str, object], directory_name: str) -> SkillDescriptor:
    name = _required_text(fields, "name", 64)
    valid_characters = True
    for character in name:
        is_alphanumeric = character.isalnum()
        if not is_alphanumeric and character != "-":
            valid_characters = False
            break
    starts_with_hyphen = name.startswith("-")
    invalid_hyphens = starts_with_hyphen
    if not invalid_hyphens:
        ends_with_hyphen = name.endswith("-")
        invalid_hyphens = ends_with_hyphen or "--" in name
    if not valid_characters or invalid_hyphens:
        raise SkillConfigurationError("name 仅支持小写字母、数字、单个连字符，且不能以连字符开头或结尾")
    lowercase_name = name.lower()
    if name != lowercase_name:
        raise SkillConfigurationError("name 仅支持小写字母、数字、单个连字符，且不能以连字符开头或结尾")
    if name != directory_name:
        raise SkillConfigurationError("name 必须与 Skill 目录名完全一致")
    description = _required_text(fields, "description", 1024)
    stripped_description = description.strip()
    descriptor = SkillDescriptor(name, stripped_description)
    return descriptor


def _parse_metadata(fields: dict[str, object]) -> SkillMetadata:
    optional: dict[str, str | None] = {}
    for key in ("license", "compatibility", "allowed-tools"):
        maximum = 500 if key == "compatibility" else None
        value = None
        if key in fields:
            value = _required_text(fields, key, maximum)
        optional[key] = value
    metadata = fields.get("metadata", {})
    is_mapping = isinstance(metadata, dict)
    if not is_mapping:
        raise SkillConfigurationError("metadata 必须是字符串到字符串的映射")
    metadata = cast(dict[str, str], metadata)
    items = metadata.items()
    for key, value in items:
        is_key_text = isinstance(key, str)
        if not is_key_text:
            raise SkillConfigurationError("metadata 必须是字符串到字符串的映射")
        is_value_text = isinstance(value, str)
        if not is_value_text:
            raise SkillConfigurationError("metadata 必须是字符串到字符串的映射")
    notices = ("allowed-tools 仅保留元数据，当前不支持其执行语义；能力由服务端静态注册。",)
    items = metadata.items()
    sorted_items = sorted(items)
    metadata_items = tuple(sorted_items)
    parsed = SkillMetadata(license=optional["license"], compatibility=optional["compatibility"], metadata=metadata_items, allowed_tools=optional["allowed-tools"], notices=notices if "allowed-tools" in fields else ())
    return parsed
