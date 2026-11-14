"""所有测试使用脱敏示例或临时库，不访问仓库真实配置与 data。"""
import json
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture
def project_root() -> Path:
    path = Path(__file__)
    resolve = path.resolve()
    return resolve.parents[2]


@pytest.fixture
def configuration(project_root: Path) -> dict[str, Any]:
    example = project_root / 'backend/config/development.example.json'
    document_text = example.read_text(encoding='utf-8')
    parsed_payload = json.loads(document_text)
    typed_value = cast(dict[str, Any], parsed_payload)
    return typed_value


@pytest.fixture
def skill_directory(tmp_path: Path) -> Path:
    """仅用于披露验证的两份测试 Skill；标记不是游戏事实，不能用于领域评估。"""
    directory = tmp_path / 'skills'
    for name, marker in (('analysis-test', 'ANALYSIS_BODY'), ('mechanics-test', 'MECHANICS_BODY')):
        skill = directory / name
        references_directory = skill / 'references'
        references_directory.mkdir(parents=True)
        skill_document = skill / 'SKILL.md'
        skill_document.write_text(f'---\nname: {name}\ndescription: 测试 {name} 的描述\n---\n{marker}\n', encoding='utf-8')
        selected_resource = skill / 'references/selected.md'
        selected_resource.write_text('SELECTED_RESOURCE', encoding='utf-8')
        unused_resource = skill / 'references/unused.md'
        unused_resource.write_text('UNUSED_RESOURCE', encoding='utf-8')
    return directory
