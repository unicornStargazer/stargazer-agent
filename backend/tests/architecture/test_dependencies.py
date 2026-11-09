"""用实际导入语法约束层间边界，防止重构重新形成巨型技术耦合包。"""

import ast
import sys
from pathlib import Path


def test_domain_only_imports_standard_library_or_domain(project_root: Path) -> None:
    source_root = project_root / "backend/src/dokkan_agent"
    violations: list[str] = []
    for path in (source_root / "domain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                allowed = module.startswith("dokkan_agent.domain")
                dependency_root = module.split(".")[0]
                forbidden_io = dependency_root in {"sqlite3", "http", "urllib"}
                if forbidden_io or (not allowed and dependency_root not in sys.stdlib_module_names):
                    violations.append(f"{path.name}: {module}")
    assert violations == []


def test_http_does_not_import_storage_or_provider(project_root: Path) -> None:
    source_root = project_root / "backend/src/dokkan_agent/interfaces/http"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("dokkan_agent.infrastructure"), path
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith("dokkan_agent.infrastructure") for alias in node.names
                ), path


def test_application_only_depends_on_domain_and_application(project_root: Path) -> None:
    source_root = project_root / "backend/src/dokkan_agent/application"
    for path in source_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module.startswith("dokkan_agent."):
                    assert module.startswith(
                        ("dokkan_agent.domain.", "dokkan_agent.application.")
                    ), path
