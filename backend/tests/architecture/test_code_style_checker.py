"""Executable examples for the custom checker, without importing application code."""

import importlib.util as importlib_util
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

TEST_PATH = Path(__file__)
TEST_PATH = TEST_PATH.resolve()
BACKEND = TEST_PATH.parents[2]
CHECKER_PATH = BACKEND / "scripts/check_code_style.py"
SPEC = importlib_util.spec_from_file_location("backend_code_style_checker", CHECKER_PATH)
assert SPEC is not None
CHECKER = importlib_util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECKER
LOADER = SPEC.loader
assert LOADER is not None
LOADER.exec_module(CHECKER)
parametrize = pytest.mark.parametrize


def diagnostics_for(source: str) -> list[Any]:
    source = textwrap.dedent(source)
    diagnostics: list[Any] = CHECKER.check_source(source, "example.py")
    return diagnostics


def codes_for(source: str) -> list[str]:
    diagnostics = diagnostics_for(source)
    return [diagnostic.code for diagnostic in diagnostics]


VALID_SOURCES = [
    "def f(a, b, c, d): pass",
    "def f(self, cls, a, /, b, *, c, d): pass",
    "def f(self, a, b, *args, **kwargs): pass",
    "async def f(cls, a, b, *, c, d): pass",
    "def f(*args, **kwargs): pass",
    "f = lambda a, b, c, d, e: a",
    """
    def f(a) -> tuple[
        int,
        str,
    ]:
        pass
    """,
    """
    async def f() -> (
        int | None
    ):
        pass
    """,
    """
    data = [
        1,
        2,
    ]
    result = consume(data)
    """,
    "result = f()",
    "result: int = f()",
    "first = second = f()",
    "first, second = f()",
    "if (result := f()): pass",
    "f()",
    "async def f():\n    result = await fetch()\n    return result",
    "async def f():\n    result: int = await fetch()",
    "async def f():\n    if (result := await fetch()): pass",
    "async def f():\n    await fetch()",
    "def f():\n    value = fetch()\n    yield value",
    "def f():\n    value = fetch()\n    yield from value",
    "items = fetch()\nfor item in items: pass",
    "async def f():\n    items = fetch()\n    async for item in items: pass",
    "manager = open_resource()\nwith manager as resource: pass",
    "async def f():\n    manager = open_resource()\n    async with manager as resource: pass",
    "owner = a.b\nowner.c()",
    "owner = a()\nowner.b()",
    "module.function()",
    "result = (factory)(1)",
    "result = (((factory)))(1)",
    "values = [1, 2]\nf(*values, **options)",
    "@register(factory(config()))\ndef f(): pass",
    "@factory().decorate(inner())\nclass Model: pass",
    "@register(factory())\nasync def f(): pass",
    "from dataclasses import field\ndef f(value=field(default_factory=list)): pass",
    "from dataclasses import field as dc_field\ndef f(value=dc_field()): pass",
    "import dataclasses as dc\ndef f(value=dc.field()): pass",
    "import dataclasses\ndef f(*, value=dataclasses.field()): pass",
    "from dataclasses import field\nvalue: list = field(default_factory=list)",
    "变量 = f(); 结果 = 对象.方法(变量)",
    "def café(参数=1): pass",
    "# f(\ntext = 'f(\\n)'\n# )",
    "def f(a='(', b=')'): pass",
    "raise Error()",
    "raise ValueError('message') from cause",
    "@pytest.mark.parametrize('value', data)\ndef f(): pass",
    "from typing import Annotated\nfrom pydantic import Field\ntype Number = Annotated[int, Field(gt=0)]",
    "from typing import Annotated as A\nfrom pydantic import StringConstraints as S\nvalue: A[str, S(min_length=1)]",
    "import typing as t\nimport pydantic as p\ndef f(value: t.Annotated[str, p.Field()]): pass",
    "from typing import Annotated\nfrom pydantic import Field\nAlias = Annotated[int, Field()]",
    "class Model:\n    model_config = ConfigDict(strict=True)",
    "from typing import Annotated, TypeAlias\nfrom pydantic import Field\nAlias: TypeAlias = Annotated[int, Field()]",
    "from typing import Annotated\nfrom pydantic import Field\nvalue: list[Annotated[int, Field()]] | None",
    "from typing import Annotated\nfrom pydantic import Field\ndef f() -> Annotated[int, Field()]: pass",
    "from dataclasses import field\nclass Data:\n    values: list = field(default_factory=list)",
]


@parametrize("source", VALID_SOURCES)
def test_accepts_valid_code(source: str) -> None:
    diagnostics = diagnostics_for(source)
    assert diagnostics == []


INVALID_SOURCES = [
    ("def f(a, b, c, d, e): pass", "CS001"),
    ("async def f(self, a, b, c, d, e): pass", "CS001"),
    ("def f(a, /, b, *, c, d, e): pass", "CS001"),
    ("def f(a, b, c, *args, **kwargs): pass", "CS001"),
    ("def f(*self, a, b, c, d): pass", "CS001"),
    ("def f(a, b, c, d, **cls): pass", "CS001"),
    ("def f(\n    a,\n): pass", "CS002"),
    ("async def f(\n): pass", "CS002"),
    ("def f(a=[\n    1,\n]): pass", "CS002"),
    ("def f \\\n    (a): pass", "CS002"),
    ("f(\n    1,\n)", "CS003"),
    ("f(\n)", "CS003"),
    ("f([\n    1,\n])", "CS003"),
    ("f(1, # comment\n  2)", "CS003"),
    ("f(1, \\\n  2)", "CS003"),
    ("def f(): return fetch()", "CS004"),
    ("def f(): yield fetch()", "CS004"),
    ("def f(): yield from fetch()", "CS004"),
    ("for item in fetch(): pass", "CS004"),
    ("async def f():\n    async for item in fetch(): pass", "CS004"),
    ("consume(fetch())", "CS004"),
    ("result = consume(fetch())", "CS004"),
    ("if fetch(): pass", "CS004"),
    ("while fetch(): pass", "CS004"),
    ("assert fetch()", "CS004"),
    ("with open_resource() as resource: pass", "CS004"),
    ("async def f():\n    async with open_resource() as resource: pass", "CS004"),
    ("async def f(): return await fetch()", "CS004"),
    ("async def f(): yield await fetch()", "CS004"),
    ("async def f(): consume(await fetch())", "CS004"),
    ("result = fetch().attribute", "CS004"),
    ("result = fetch()[0]", "CS004"),
    ("result = fetch() + 1", "CS004"),
    ("result = fetch() or fallback", "CS004"),
    ("result = [fetch()]", "CS004"),
    ("result = [fetch() for item in items]", "CS004"),
    ("result = f'{fetch()}'", "CS004"),
    ("result = 1 if fetch() else 0", "CS004"),
    ("raise Error(fetch())", "CS004"),
    ("def f(value=factory()): pass", "CS004"),
    ("async def f(*, value=factory()): pass", "CS004"),
    ("def f(value: annotation()): pass", "CS004"),
    ("def f() -> annotation(): pass", "CS004"),
    ("from dataclasses import field\ndef f(value=field(default=make())): pass", "CS004"),
    ("from dataclasses import field\ndef f(value=[field()]): pass", "CS004"),
    ("def f(value=field()): pass", "CS004"),
    ("import other as dataclasses\ndef f(value=dataclasses.field()): pass", "CS004"),
    ("from other import field\ndef f(value=field()): pass", "CS004"),
    ("if True:\n    from dataclasses import field\ndef f(value=field()): pass", "CS004"),
    ("a.b.c()", "CS005"),
    ("a().b()", "CS005"),
    ("package.module.function()", "CS005"),
    ("result = package.module.function()", "CS005"),
    ("@register()\ndef f():\n    package.framework.register()", "CS005"),
    ("@register(\n    value,\n)\ndef f(): pass", "CS003"),
    ("from dataclasses import field\ndef f(value=field(\n)): pass", "CS003"),
    ("from typing import Annotated\nfrom pydantic import Field\ntype Alias = Annotated[int, Field(default=make())]", "CS004"),
    ("from typing import Annotated\nfrom pydantic import Field\nconsume(Annotated[int, Field()])", "CS004"),
    ("from typing import Annotated\nfrom other import Field\ntype Alias = Annotated[int, Field()]", "CS004"),
    ("from typing import Annotated\nfrom pydantic import Field\ntype Alias = Annotated[int, Field(\n)]", "CS003"),
    ("class Model:\n    model_config = ConfigDict(value=make())", "CS004"),
    ("raise Error() from cause()", "CS004"),
    ("async def f(): raise await make()", "CS004"),
    ("from typing import Annotated\nfrom pydantic import Field\nvalue: Annotated[Field(), int]", "CS004"),
    ("class Model:\n    model_config = ConfigDict(\n        strict=True,\n    )", "CS003"),
]


@parametrize("source, expected_code", INVALID_SOURCES)
def test_rejects_invalid_code(source: str, expected_code: str) -> None:
    codes = codes_for(source)
    assert expected_code in codes


def test_diagnostic_path_line_and_codes_are_stable() -> None:
    source = "\ndef f(a, b, c, d, e):\n    return outer(inner())\n"
    diagnostics = diagnostics_for(source)
    locations = [(item.path, item.line, item.code) for item in diagnostics]
    expected = [
        ("example.py", 2, "CS001"),
        ("example.py", 3, "CS004"),
        ("example.py", 3, "CS004"),
    ]
    assert locations == expected
    rendered = str(diagnostics[0])
    matches = rendered.startswith("example.py:2:CS001: ")
    assert matches


def test_syntax_error_is_a_diagnostic() -> None:
    diagnostics = diagnostics_for("def broken(:\n    pass")
    assert diagnostics[0].code == "CS000"
    assert diagnostics[0].line == 1


def test_pep695_bounds_do_not_confuse_signature_location() -> None:
    source = "def f[T: tuple[int, str]](\n    value: T,\n): pass"
    codes = codes_for(source)
    assert codes == ["CS002"]


def test_unicode_before_parenthesized_callable() -> None:
    source = "变量 = 1; 结果 = (函数)(\n    变量,\n)"
    diagnostics = diagnostics_for(source)
    assert diagnostics[0].code == "CS003"
    assert diagnostics[0].line == 1


def test_assignment_does_not_exempt_calls_inside_its_expression() -> None:
    codes = codes_for("result = outer(inner())")
    assert codes == ["CS004"]
    codes = codes_for("factory()()")
    assert codes == ["CS004"]


def test_decorator_exemption_does_not_leak_into_function_body() -> None:
    source = "@factory(inner())\ndef f():\n    return inner()"
    diagnostics = diagnostics_for(source)
    count = len(diagnostics)
    assert count == 1
    assert diagnostics[0].line == 3


def run_cli(paths: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    checker_path = str(CHECKER_PATH)
    command = [sys.executable, checker_path, *paths]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return result


def test_cli_exit_codes_and_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def f(): return fetch()\n", encoding="utf-8")
    filename = str(source)
    result = run_cli([filename], tmp_path)
    assert result.returncode == 1
    assert f"{source}:1:CS004:" in result.stdout
    source.write_text("value = fetch()\n", encoding="utf-8")
    result = run_cli([filename], tmp_path)
    assert result.returncode == 0
    assert "Checked 1 Python file(s); 0 violation(s)." in result.stdout


def test_cli_reports_missing_and_invalid_inputs(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    filename = str(missing)
    result = run_cli([filename], tmp_path)
    assert result.returncode == 1
    assert "CS000" in result.stdout
    missing.write_text("def broken(:", encoding="utf-8")
    result = run_cli([filename], tmp_path)
    assert result.returncode == 1
    assert "CS000" in result.stdout


def test_discovery_recurses_excludes_and_deduplicates(tmp_path: Path) -> None:
    source = tmp_path / "ok.py"
    source.write_text("value = fetch()", encoding="utf-8")
    names = [".venv", "__pycache__", "dist", "node_modules", "generated"]
    for name in names:
        directory = tmp_path / name
        directory.mkdir()
        hidden = directory / "bad.py"
        hidden.write_text("return fetch()", encoding="utf-8")
    ignored = tmp_path / "README.txt"
    ignored.write_text("not python", encoding="utf-8")
    directory_name = str(tmp_path)
    filename = str(source)
    arguments = [directory_name, filename, "--exclude", "generated"]
    result = run_cli(arguments, tmp_path)
    assert result.returncode == 0
    assert "Checked 1 Python file(s)" in result.stdout


def test_discovery_rejects_missing_paths(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    excluded = CHECKER.EXCLUDED_DIRECTORIES
    files, diagnostics = CHECKER.discover_files([missing], excluded)
    assert files == []
    assert diagnostics[0].code == "CS000"


def test_file_read_errors_and_encoding_cookies(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_bytes(b"# coding: latin-1\nname = 'caf\xe9'\nresult = f()\n")
    diagnostics = CHECKER.check_file(source)
    assert diagnostics == []
    source.write_bytes(b"\xef\xbb\xbfresult = f()\n")
    diagnostics = CHECKER.check_file(source)
    assert diagnostics == []
    source.write_bytes(b"\xff\xfe\xff")
    diagnostics = CHECKER.check_file(source)
    assert diagnostics[0].code == "CS000"
    source.unlink()
    diagnostics = CHECKER.check_file(source)
    assert diagnostics[0].code == "CS000"


def test_default_paths_are_backend_relative() -> None:
    paths = CHECKER.default_paths()
    expected = [BACKEND / name for name in ("src", "tests", "examples", "scripts")]
    assert paths == expected
    excluded = CHECKER.EXCLUDED_DIRECTORIES
    files, diagnostics = CHECKER.discover_files(paths, excluded)
    assert diagnostics == []
    assert CHECKER_PATH in files
    assert TEST_PATH in files
    for path in paths:
        matches = [candidate for candidate in files if path in candidate.parents]
        assert matches


def test_all_backend_python_follows_code_style() -> None:
    paths = CHECKER.default_paths()
    excluded = CHECKER.EXCLUDED_DIRECTORIES
    files, diagnostics = CHECKER.discover_files(paths, excluded)
    for path in files:
        issues = CHECKER.check_file(path)
        diagnostics.extend(issues)
    messages: list[str] = []
    for issue in diagnostics:
        message = str(issue)
        messages.append(message)
    report = "\n".join(messages)
    assert diagnostics == [], report


def test_checker_and_its_tests_follow_their_own_rules() -> None:
    for path in (CHECKER_PATH, TEST_PATH):
        diagnostics = CHECKER.check_file(path)
        assert diagnostics == []
