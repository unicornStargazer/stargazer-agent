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
        return tuple(
            SkillResource(item.relative_path, item.digest, _resource_kind(item.relative_path))
            for item in self.files
            if item.relative_path.split("/")[0] in {"references", "assets", "scripts"}
        )


def read_bounded_file(path: Path) -> bytes:
    """即使扫描后文件变大，读取也有硬上限；二进制文件只参与版本校验。"""
    with path.open("rb") as handle:
        content = handle.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise SkillConfigurationError("Skill 单文件超过部署上限 1 MiB")
    return content


def scan_skill(root: Path) -> SkillSnapshot:
    """冻结整个 Skill 内容及真实路径，发现外链/目录链接立即拒绝，避免递归环。"""
    records: list[FileSnapshot] = []
    for directory, subdirectories, filenames in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
        _validate_subdirectories(Path(directory), subdirectories)
        for filename in sorted(filenames):
            path = Path(directory) / filename
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise SkillConfigurationError("Skill 资源必须是根目录内的普通文件")
            content = read_bounded_file(resolved)
            records.append(
                FileSnapshot(
                    path.relative_to(root).as_posix(), resolved, hashlib.sha256(content).hexdigest()
                )
            )
            if len(records) > MAX_SKILL_FILES:
                raise SkillConfigurationError("单个 Skill 超过 256 个部署文件")
    document = read_bounded_file(root / "SKILL.md").decode("utf-8-sig")
    parsed = parse_skill_document(document, root.name)
    return SkillSnapshot(
        root,
        parsed.descriptor,
        parsed.metadata,
        tuple(sorted(records, key=lambda item: item.relative_path)),
    )


def _validate_subdirectories(directory: Path, subdirectories: list[str]) -> None:
    for name in subdirectories:
        path = directory / name
        if path.is_symlink() or path.is_junction():
            raise SkillConfigurationError("Skill 内不支持目录符号链接或 junction")


def _raise_walk_error(error: OSError) -> NoReturn:
    raise error


def _resource_kind(relative_path: str) -> Literal["text", "binary", "script"]:
    if relative_path.startswith("scripts/"):
        return "script"
    return "text" if Path(relative_path).suffix.lower() in TEXT_SUFFIXES else "binary"
