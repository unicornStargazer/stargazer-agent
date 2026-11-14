"""部署快照只保存描述、元数据和哈希；正文在激活时读取，不缓存进 Catalog。"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

from dokkan_agent.domain.skill.errors import SkillConfigurationError
from dokkan_agent.domain.skill.models import SkillDescriptor, SkillMetadata, SkillResource
from dokkan_agent.infrastructure.skill.frontmatter import parse_skill_document

MAX_FILE_BYTES = 1_048_576
MAX_SKILL_FILES = 256
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".xml", ".rst"}


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    relative_path: str
    resolved_path: Path
    digest: str


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    root: Path
    descriptor: SkillDescriptor
    metadata: SkillMetadata
    files: tuple[FileSnapshot, ...]

    @property
    def resources(self) -> tuple[SkillResource, ...]:
        resources: list[SkillResource] = []
        for item in self.files:
            relative_path = item.relative_path
            parts = relative_path.split("/")
            if parts[0] in {"references", "assets", "scripts"}:
                kind = _resource_kind(item.relative_path)
                resource = SkillResource(item.relative_path, item.digest, kind)
                resources.append(resource)
        result = tuple(resources)
        return result


def read_bounded_file(path: Path) -> bytes:
    """即使扫描后文件变大，读取也有硬上限；二进制文件只参与版本校验。"""
    file_context = path.open("rb")
    with file_context as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    size = len(content)
    if size > MAX_FILE_BYTES:
        raise SkillConfigurationError("Skill 单文件超过部署上限 1 MiB")
    return content


def scan_skill(root: Path) -> SkillSnapshot:
    """冻结整个 Skill 内容及真实路径，发现外链/目录链接立即拒绝，避免递归环。"""
    records: list[FileSnapshot] = []
    directories = os.walk(root, followlinks=False, onerror=_raise_walk_error)
    for directory, subdirectories, filenames in directories:
        directory_path = Path(directory)
        _validate_subdirectories(directory_path, subdirectories)
        sorted_filenames = sorted(filenames)
        for filename in sorted_filenames:
            path = directory_path / filename
            resolved = path.resolve(strict=True)
            is_relative = resolved.is_relative_to(root)
            if not is_relative:
                raise SkillConfigurationError("Skill 资源必须是根目录内的普通文件")
            is_file = resolved.is_file()
            if not is_file:
                raise SkillConfigurationError("Skill 资源必须是根目录内的普通文件")
            content = read_bounded_file(resolved)
            relative = path.relative_to(root)
            relative_path = relative.as_posix()
            digest_builder = hashlib.sha256(content)
            digest = digest_builder.hexdigest()
            record = FileSnapshot(relative_path, resolved, digest)
            records.append(record)
            record_count = len(records)
            if record_count > MAX_SKILL_FILES:
                raise SkillConfigurationError("单个 Skill 超过 256 个部署文件")
    document_bytes = read_bounded_file(root / "SKILL.md")
    document = document_bytes.decode("utf-8-sig")
    parsed = parse_skill_document(document, root.name)
    sorted_records = sorted(records, key=lambda item: item.relative_path)
    snapshot_files = tuple(sorted_records)
    snapshot = SkillSnapshot(root, parsed.descriptor, parsed.metadata, snapshot_files)
    return snapshot


def _validate_subdirectories(directory: Path, subdirectories: list[str]) -> None:
    for name in subdirectories:
        path = directory / name
        is_link = path.is_symlink()
        if not is_link:
            is_link = path.is_junction()
        if is_link:
            raise SkillConfigurationError("Skill 内不支持目录符号链接或 junction")


def _raise_walk_error(error: OSError) -> NoReturn:
    raise error


def _resource_kind(relative_path: str) -> Literal["text", "binary", "script"]:
    is_script = relative_path.startswith("scripts/")
    if is_script:
        return "script"
    path = Path(relative_path)
    suffix = path.suffix
    normalized_suffix = suffix.lower()
    return "text" if normalized_suffix in TEXT_SUFFIXES else "binary"
