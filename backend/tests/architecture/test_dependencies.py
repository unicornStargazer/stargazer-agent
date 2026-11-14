"""用实际导入语法约束层间边界，防止重构重新形成巨型技术耦合包。"""

import ast
import sys
from pathlib import Path


def test_domain_only_imports_standard_library_or_domain(project_root: Path) -> None:
    source_root = project_root / 'backend/src/dokkan_agent'
    violations: list[str] = []
    domain_root = source_root / 'domain'
    source_paths = domain_root.rglob('*.py')
    for path in source_paths:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        nodes = ast.walk(tree)
        for node in nodes:
            modules: list[str] = []
            match node:
                case ast.Import():
                    modules = [alias.name for alias in node.names]
                case ast.ImportFrom():
                    modules = [node.module or '']
            for module in modules:
                allowed = module.startswith('dokkan_agent.domain')
                components = module.split('.')
                dependency_root = components[0]
                forbidden_io = dependency_root in {'sqlite3', 'http', 'urllib'}
                if forbidden_io or (not allowed and dependency_root not in sys.stdlib_module_names):
                    violations.append(f'{path.name}: {module}')
    assert violations == []


def test_http_does_not_import_storage_or_provider(project_root: Path) -> None:
    source_root = project_root / 'backend/src/dokkan_agent/interfaces/http'
    source_paths = source_root.rglob('*.py')
    for path in source_paths:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        nodes = ast.walk(tree)
        for node in nodes:
            match node:
                case ast.ImportFrom():
                    module = node.module or ''
                    infrastructure_import = module.startswith('dokkan_agent.infrastructure')
                    assert not infrastructure_import, path
                case ast.Import():
                    allowed_imports = []
                    for alias in node.names:
                        name = alias.name
                        infrastructure_import = name.startswith('dokkan_agent.infrastructure')
                        allowed_imports.append(not infrastructure_import)
                    all_allowed = all(allowed_imports)
                    assert all_allowed, path


def test_application_only_depends_on_domain_and_application(project_root: Path) -> None:
    source_root = project_root / 'backend/src/dokkan_agent/application'
    source_paths = source_root.rglob('*.py')
    for path in source_paths:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        nodes = ast.walk(tree)
        for node in nodes:
            modules: list[str] = []
            match node:
                case ast.ImportFrom():
                    modules = [node.module or '']
                case ast.Import():
                    modules = [alias.name for alias in node.names]
            for module in modules:
                internal_import = module.startswith('dokkan_agent.')
                if internal_import:
                    allowed_import = module.startswith(('dokkan_agent.domain.', 'dokkan_agent.application.'))
                    assert allowed_import, path
