"""文件系统 Catalog：只从显式运行目录发现 Skill，不扫描开发辅助 Skill。"""

import asyncio
import hashlib
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath

from dokkan_agent.domain.skill.errors import SkillAccessError, SkillConfigurationError
from dokkan_agent.domain.skill.models import (
    ActivatedSkill,
    LoadedSkillResource,
    SkillDescriptor,
    SkillMetadata,
)
from dokkan_agent.domain.tool.models import ToolErrorCode
from dokkan_agent.infrastructure.skill.frontmatter import parse_skill_document
from dokkan_agent.infrastructure.skill.snapshot import SkillSnapshot, read_bounded_file, scan_skill

LOGGER = logging.getLogger(__name__)


class FilesystemSkillCatalog:
    """保存部署快照；每次披露复查全部文件，修改后需重启，文件 IO 移交工作线程。"""

    def __init__(self, snapshots: tuple[SkillSnapshot, ...]) -> None:
        self._snapshots = {item.descriptor.name: item for item in snapshots}
        if len(self._snapshots) != len(snapshots):
            raise SkillConfigurationError("存在重复的 Skill 名称")

    @classmethod
    def discover(cls, directory: Path) -> "FilesystemSkillCatalog":
        """启动发现；不存在或非法 Skill 使部署失败，不静默跳过已配置的内容。"""
        try:
            root = directory.resolve(strict=True)
            snapshots: list[SkillSnapshot] = []
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                if child.is_symlink() or child.is_junction():
                    raise SkillConfigurationError(f"Skill 目录不能是链接：{child}")
                if not (child / "SKILL.md").is_file():
                    raise SkillConfigurationError(f"目录缺少 SKILL.md：{child}")
                try:
                    snapshot = scan_skill(child.resolve())
                    snapshots.append(snapshot)
                    for notice in snapshot.metadata.notices:
                        LOGGER.warning("Skill %s：%s", snapshot.descriptor.name, notice)
                except SkillConfigurationError as error:
                    raise SkillConfigurationError(f"Skill 无效：{child}；{error}") from None
                except (ValueError, OSError, UnicodeError, RuntimeError) as error:
                    raise SkillConfigurationError(
                        f"Skill 无效：{child}；{type(error).__name__}"
                    ) from None
            return cls(tuple(snapshots))
        except (OSError, UnicodeError):
            raise SkillConfigurationError(f"无法读取 Skill 运行目录：{directory}") from None

    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        return tuple(item.descriptor for item in self._snapshots.values())

    def metadata(self, name: str) -> SkillMetadata:
        """供启动诊断展示兼容性提示；这些信息不自动进入 L1 模型上下文。"""
        return self._get_snapshot(name).metadata

    async def load_skill(self, name: str) -> ActivatedSkill:
        snapshot = self._get_snapshot(name)
        return await asyncio.to_thread(self._load_verified_skill, snapshot)

    async def read_resource(self, name: str, relative_path: str) -> LoadedSkillResource:
        snapshot = self._get_snapshot(name)
        self._validate_relative_path(relative_path)
        return await asyncio.to_thread(self._read_verified_resource, snapshot, relative_path)

    def _get_snapshot(self, name: str) -> SkillSnapshot:
        snapshot = self._snapshots.get(name)
        if snapshot is None:
            raise SkillAccessError(ToolErrorCode.UNKNOWN_SKILL, "请求的 Skill 不在目录中。")
        return snapshot

    def _verify_snapshot(self, snapshot: SkillSnapshot) -> None:
        try:
            if (
                snapshot.root.resolve(strict=True) != snapshot.root
                or scan_skill(snapshot.root) != snapshot
            ):
                raise SkillConfigurationError("部署文件变化")
        except (ValueError, OSError, UnicodeError, RuntimeError):
            raise SkillAccessError(
                ToolErrorCode.SKILL_CHANGED, "Skill 部署文件已变化，请重启服务。"
            ) from None

    def _load_verified_skill(self, snapshot: SkillSnapshot) -> ActivatedSkill:
        self._verify_snapshot(snapshot)
        document = self._read_verified_file(snapshot, "SKILL.md")
        parsed = parse_skill_document(document, snapshot.descriptor.name)
        version = next(item.digest for item in snapshot.files if item.relative_path == "SKILL.md")
        return ActivatedSkill(snapshot.descriptor, parsed.instructions, version, snapshot.resources)

    def _read_verified_resource(
        self, snapshot: SkillSnapshot, relative_path: str
    ) -> LoadedSkillResource:
        self._verify_snapshot(snapshot)
        resource = next(
            (item for item in snapshot.resources if item.relative_path == relative_path), None
        )
        if resource is None:
            raise SkillAccessError(ToolErrorCode.RESOURCE_NOT_FOUND, "资源不在 Skill 注册清单中。")
        if resource.kind != "text":
            raise SkillAccessError(
                ToolErrorCode.RESOURCE_PATH_INVALID, "脚本和二进制资源仅列元信息，不读取或执行。"
            )
        return LoadedSkillResource(
            snapshot.descriptor.name, resource, self._read_verified_file(snapshot, relative_path)
        )

    @staticmethod
    def _read_verified_file(snapshot: SkillSnapshot, relative_path: str) -> str:
        try:
            expected = next(item for item in snapshot.files if item.relative_path == relative_path)
            path = (snapshot.root / relative_path).resolve(strict=True)
            if not path.is_relative_to(snapshot.root) or path != expected.resolved_path:
                raise ValueError("路径变化")
            content = read_bounded_file(path)
            if hashlib.sha256(content).hexdigest() != expected.digest:
                raise ValueError("内容变化")
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise SkillAccessError(
                ToolErrorCode.RESOURCE_PATH_INVALID, "资源不是 UTF-8 文本，请选择其他已登记资源。"
            ) from None
        except (ValueError, OSError):
            raise SkillAccessError(
                ToolErrorCode.SKILL_CHANGED, "Skill 内容或编码已变化，请检查并重启服务。"
            ) from None

    @staticmethod
    def _validate_relative_path(value: str) -> None:
        path = PurePosixPath(value)
        invalid = not value or "\\" in value or ":" in value or "\x00" in value
        if (
            invalid
            or path.is_absolute()
            or PureWindowsPath(value).is_absolute()
            or ".." in path.parts
        ):
            raise SkillAccessError(
                ToolErrorCode.RESOURCE_PATH_INVALID, "必须使用 Skill 内登记的相对资源路径。"
            )
        if path.as_posix() != value or value.startswith("./"):
            raise SkillAccessError(
                ToolErrorCode.RESOURCE_PATH_INVALID, "资源路径必须使用规范的相对路径。"
            )
