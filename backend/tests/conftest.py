"""所有测试使用脱敏示例或临时库，不访问仓库真实配置与 data。"""

import json
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def configuration(project_root: Path) -> dict[str, Any]:
    example = project_root / "backend/config/development.example.json"
    return cast(dict[str, Any], json.loads(example.read_text(encoding="utf-8")))


@pytest.fixture
def skill_directory(tmp_path: Path) -> Path:
    """仅用于披露验证的两份测试 Skill；标记不是游戏事实，不能用于领域评估。"""
    directory = tmp_path / "skills"
    for name, marker in (("analysis-test", "ANALYSIS_BODY"), ("mechanics-test", "MECHANICS_BODY")):
        skill = directory / name
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: 测试 {name} 的描述\n---\n{marker}\n",
            encoding="utf-8",
        )
        (skill / "references/selected.md").write_text("SELECTED_RESOURCE", encoding="utf-8")
        (skill / "references/unused.md").write_text("UNUSED_RESOURCE", encoding="utf-8")
    return directory
