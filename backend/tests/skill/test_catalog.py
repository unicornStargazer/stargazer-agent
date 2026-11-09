"""Skill 格式、三层数据边界、部署变化和文件读取边界验证。"""

import asyncio
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from dokkan_agent.domain.skill.errors import SkillAccessError, SkillConfigurationError
from dokkan_agent.domain.tool.models import ToolErrorCode
from dokkan_agent.infrastructure.skill.filesystem_catalog import FilesystemSkillCatalog
from dokkan_agent.infrastructure.skill.frontmatter import parse_skill_document


async def test_catalog_never_discloses_unactivated_body_or_resource(skill_directory: Path) -> None:
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    level_one = json.dumps([asdict(item) for item in catalog.descriptors()])
    assert "analysis-test" in level_one
    assert "ANALYSIS_BODY" not in level_one
    assert "SELECTED_RESOURCE" not in level_one
    activated = await catalog.load_skill("analysis-test")
    assert activated.instructions == "ANALYSIS_BODY"
    assert {item.relative_path for item in activated.resources} == {
        "references/selected.md",
        "references/unused.md",
    }
    assert "SELECTED_RESOURCE" not in repr(activated)
    resource = await catalog.read_resource("analysis-test", "references/selected.md")
    assert resource.content == "SELECTED_RESOURCE"


@pytest.mark.parametrize(
    "header",
    [
        "name: analysis-test\n",
        "name: analysis-test\ndescription: ''\n",
        "name: analysis-test\ndescription: valid\ndescription: duplicate\n",
        "name: WrongName\ndescription: valid\n",
        "name: wrong--name\ndescription: valid\n",
        "name: ../analysis-test\ndescription: valid\n",
        "name: analysis-test\ndescription: valid\nmetadata: {number: 1}\n",
        "name: analysis-test\ndescription: valid\nmetadata: {x: a, x: b}\n",
        "name: analysis-test\ndescription: valid\nlicense: &x value\ncompatibility: *x\n",
        "name: analysis-test\ndescription: !!python/object:os.system {}\n",
        "name: analysis-test\ndescription: valid\nmodel: unexpected\n",
    ],
)
def test_invalid_frontmatter_fails_explicitly(header: str) -> None:
    with pytest.raises(SkillConfigurationError):
        parse_skill_document(f"---\n{header}---\n正文", "analysis-test")


def test_standard_optional_metadata_is_preserved_without_tool_authority() -> None:
    parsed = parse_skill_document(
        "---\nname: analysis-test\ndescription: 有效描述\nlicense: MIT\n"
        "compatibility: 需要文本输入\nmetadata: {version: '1.0'}\n"
        "allowed-tools: Bash Read\n---\n正文",
        "analysis-test",
    )
    assert parsed.metadata.license == "MIT"
    assert parsed.metadata.metadata == (("version", "1.0"),)
    assert parsed.metadata.allowed_tools == "Bash Read"
    assert "不支持" in parsed.metadata.notices[0]


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.txt",
        "/etc/passwd",
        "C:/secret.txt",
        "C:secret.txt",
        "references/../../secret",
        "references\\selected.md",
        "./references/selected.md",
        "references//selected.md",
        "references/selected.md\x00",
    ],
)
async def test_invalid_resource_paths_do_not_read_files(
    skill_directory: Path, relative_path: str
) -> None:
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    with pytest.raises(SkillAccessError) as captured:
        await catalog.read_resource("analysis-test", relative_path)
    assert captured.value.code == ToolErrorCode.RESOURCE_PATH_INVALID


@pytest.mark.parametrize("mutation", ["body", "resource", "add", "remove"])
async def test_changed_deployment_requires_restart(skill_directory: Path, mutation: str) -> None:
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    skill = skill_directory / "analysis-test"
    if mutation == "body":
        with (skill / "SKILL.md").open("a", encoding="utf-8") as handle:
            handle.write("变更正文")
    elif mutation == "resource":
        (skill / "references/selected.md").write_text("变更资源", encoding="utf-8")
    elif mutation == "add":
        (skill / "references/new.md").write_text("新资源", encoding="utf-8")
    else:
        (skill / "references/unused.md").unlink()
    with pytest.raises(SkillAccessError) as captured:
        await catalog.load_skill("analysis-test")
    assert captured.value.code == ToolErrorCode.SKILL_CHANGED
    assert "重启" in str(captured.value)


async def test_scripts_and_binary_assets_are_metadata_only(skill_directory: Path) -> None:
    skill = skill_directory / "analysis-test"
    (skill / "scripts").mkdir()
    (skill / "scripts/action.py").write_text(
        "raise RuntimeError('never executed')", encoding="utf-8"
    )
    (skill / "assets").mkdir()
    (skill / "assets/picture.png").write_bytes(b"\x89PNG\x00\xff")
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    activated = await catalog.load_skill("analysis-test")
    kinds = {item.relative_path: item.kind for item in activated.resources}
    assert kinds["scripts/action.py"] == "script"
    assert kinds["assets/picture.png"] == "binary"
    for name in ("scripts/action.py", "assets/picture.png"):
        with pytest.raises(SkillAccessError) as captured:
            await catalog.read_resource("analysis-test", name)
        assert captured.value.code == ToolErrorCode.RESOURCE_PATH_INVALID


async def test_external_symlink_is_rejected_at_discovery_or_runtime(
    skill_directory: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("MUST_NOT_DISCLOSE", encoding="utf-8")
    path = skill_directory / "analysis-test/references/link.md"
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 未授权创建文件符号链接；其他路径边界用例仍执行")
    with pytest.raises(SkillConfigurationError):
        FilesystemSkillCatalog.discover(skill_directory)
    path.unlink()
    path.write_text("注册时的文本", encoding="utf-8")
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(SkillAccessError) as captured:
        await catalog.read_resource("analysis-test", "references/link.md")
    assert captured.value.code == ToolErrorCode.SKILL_CHANGED


def test_directory_name_mismatch_reports_file_location(skill_directory: Path) -> None:
    path = skill_directory / "analysis-test/SKILL.md"
    path.write_text("---\nname: other\ndescription: valid\n---\nbody", encoding="utf-8")
    with pytest.raises(SkillConfigurationError) as captured:
        FilesystemSkillCatalog.discover(skill_directory)
    assert "analysis-test" in str(captured.value)
    assert "目录名" in str(captured.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 专项")
async def test_directory_junction_cannot_escape_skill_root(
    skill_directory: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.md").write_text("MUST_NOT_DISCLOSE", encoding="utf-8")
    link = skill_directory / "analysis-test/references/external"
    # 只在 pytest 临时目录创建 junction；不跨 shell 删除/移动文件。
    await asyncio.to_thread(_create_junction, link, outside)
    with pytest.raises(SkillConfigurationError):
        FilesystemSkillCatalog.discover(skill_directory)
    link.rmdir()
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    await asyncio.to_thread(_create_junction, link, outside)
    try:
        with pytest.raises(SkillAccessError) as captured:
            await catalog.load_skill("analysis-test")
        assert captured.value.code == ToolErrorCode.SKILL_CHANGED
    finally:
        link.rmdir()


def _create_junction(link: Path, target: Path) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        timeout=5,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


async def test_non_utf8_resource_returns_safe_error_without_partial_text(
    skill_directory: Path,
) -> None:
    path = skill_directory / "analysis-test/references/non-utf8.md"
    path.write_bytes(b"PREFIX_MUST_NOT_LEAK\xff")
    catalog = FilesystemSkillCatalog.discover(skill_directory)
    with pytest.raises(SkillAccessError) as captured:
        await catalog.read_resource("analysis-test", "references/non-utf8.md")
    assert captured.value.code == ToolErrorCode.RESOURCE_PATH_INVALID
    assert "UTF-8" in str(captured.value)
    assert "PREFIX_MUST_NOT_LEAK" not in str(captured.value)


def test_unicode_lowercase_skill_name_follows_standard_format() -> None:
    parsed = parse_skill_document(
        "---\nname: café-analysis\ndescription: 示例\n---\n正文", "café-analysis"
    )
    assert parsed.descriptor.name == "café-analysis"
