#!/usr/bin/env python3
"""Check the backend's local style rules using only the Python standard library."""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import os
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIRECTORIES = ("src", "tests", "examples", "scripts")
_EXCLUDED_NAMES = {
    ".venv", "venv", "env", ".git", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".nox", "node_modules", "build", "dist", "site-packages",
}
EXCLUDED_DIRECTORIES = frozenset(_EXCLUDED_NAMES)


@dataclass(frozen=True, order=True)
class Diagnostic:
    path: str
    line: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.code}: {self.message}"


class StyleChecker:
    def __init__(self, tree: ast.Module, source: str, path: str) -> None:
        self.tree = tree
        self.path = path
        self.lines = source.splitlines(keepends=True)
        self.diagnostics: list[Diagnostic] = []
        self.parents: dict[ast.AST, ast.AST] = {}
        self.decorators: set[ast.AST] = set()
        self.default_factories: set[str] = set()
        self.dataclass_modules: set[str] = set()
        self.declaration_imports: dict[str, str] = {}
        stream = io.StringIO(source)
        reader = stream.readline
        token_stream = tokenize.generate_tokens(reader)
        self.tokens = list(token_stream)
        tokens = self.tokens
        self.positions = [token.start for token in tokens]
        self.pairs: dict[int, int] = {}
        self._index_tree()
        self._index_brackets()
        self._index_dataclass_imports()

    def _index_tree(self) -> None:
        parents = self.parents
        decorators = self.decorators
        tree = self.tree
        nodes = ast.walk(tree)
        for node in nodes:
            children = ast.iter_child_nodes(node)
            for child in children:
                parents[child] = node
            match node:
                case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                    for decorator in node.decorator_list:
                        descendants = ast.walk(decorator)
                        decorators.update(descendants)

    def _index_brackets(self) -> None:
        stack: list[int] = []
        tokens = self.tokens
        pairs = self.pairs
        indexed_tokens = enumerate(tokens)
        for index, token in indexed_tokens:
            if token.type != tokenize.OP:
                continue
            if token.string in {"(", "[", "{"}:
                stack.append(index)
            elif token.string in {")", "]", "}"}:
                opening = stack.pop()
                pairs[opening] = index

    def _index_dataclass_imports(self) -> None:
        tree = self.tree
        factories = self.default_factories
        modules = self.dataclass_modules
        declarations = self.declaration_imports
        recognized = {"typing", "typing_extensions", "pydantic"}
        for node in tree.body:
            match node:
                case ast.ImportFrom(module=module, level=0) if module in recognized:
                    for alias in node.names:
                        declarations[alias.asname or alias.name] = f"{module}.{alias.name}"
                case ast.Import():
                    for alias in node.names:
                        if alias.name in recognized:
                            declarations[alias.asname or alias.name] = alias.name
            match node:
                case ast.ImportFrom(module="dataclasses", level=0):
                    for alias in node.names:
                        if alias.name == "field":
                            factories.add(alias.asname or alias.name)
                case ast.Import():
                    for alias in node.names:
                        if alias.name == "dataclasses":
                            modules.add(alias.asname or alias.name)

    def _position(self, node: ast.AST, end: bool = False) -> tuple[int, int]:
        if end:
            line, column = node.end_lineno, node.end_col_offset
        else:
            line, column = node.lineno, node.col_offset
        lines = self.lines
        text = lines[line - 1]
        encoded = text.encode("utf-8")
        prefix = encoded[:column]
        decoded = prefix.decode("utf-8")
        character_column = len(decoded)
        return line, character_column

    def _opening(self, node: ast.AST) -> int:
        match node:
            case ast.Call():
                position = self._position(node.func, end=True)
            case _:
                position = self._position(node)
        positions = self.positions
        index = bisect.bisect_left(positions, position)
        tokens = self.tokens
        pairs = self.pairs
        size = len(tokens)
        while index < size:
            token = tokens[index]
            if token.string == "(":
                return index
            # Skip a PEP 695 type-parameter list, including its bounds/defaults.
            if token.type == tokenize.OP and token.string == "[":
                index = pairs[index]
            index += 1
        raise ValueError("Cannot locate argument-list parentheses in valid Python")

    def _report(self, node: ast.AST, code: str, message: str) -> None:
        path = self.path
        issue = Diagnostic(path, node.lineno, code, message)
        diagnostics = self.diagnostics
        diagnostics.append(issue)

    def _check_definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        arguments = node.args
        ordinary = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
        counted = (argument.arg not in {"self", "cls"} for argument in ordinary)
        count = sum(counted)
        if arguments.vararg is not None:
            count += 1
        if arguments.kwarg is not None:
            count += 1
        if count > 4:
            self._report(node, "CS001", f"Definition has {count} parameters; maximum is 4 (excluding self/cls)")
        opening = self._opening(node)
        pairs = self.pairs
        closing = pairs[opening]
        tokens = self.tokens
        end_token = tokens[closing]
        if node.lineno != end_token.end[0]:
            self._report(node, "CS002", "Definition parameters must be on one line; move multiline defaults to variables")

    def _is_field_default(self, node: ast.Call) -> bool:
        parents = self.parents
        parent = parents.get(node)
        match parent:
            case ast.arguments():
                defaults = parent.defaults + parent.kw_defaults
                if node not in defaults:
                    return False
            case _:
                return False
        factories = self.default_factories
        modules = self.dataclass_modules
        match node.func:
            case ast.Name(id=name):
                return name in factories
            case ast.Attribute(value=ast.Name(id=name), attr="field"):
                return name in modules
        return False

    def _declaration_name(self, node: ast.AST) -> str:
        declarations = self.declaration_imports
        match node:
            case ast.Name(id=name):
                resolved = declarations.get(name, "")
                return resolved
            case ast.Attribute(value=ast.Name(id=name), attr=attribute):
                module = declarations.get(name, "")
                return f"{module}.{attribute}"
        return ""

    def _is_annotated_metadata(self, node: ast.Call) -> bool:
        name = self._declaration_name(node.func)
        if name not in {"pydantic.Field", "pydantic.StringConstraints"}:
            return False
        parents = self.parents
        metadata = parents.get(node)
        match metadata:
            case ast.Tuple(elts=elements):
                if node not in elements[1:]:
                    return False
            case _:
                return False
        annotation = parents.get(metadata)
        match annotation:
            case ast.Subscript(slice=value) if value is metadata:
                name = self._declaration_name(annotation.value)
            case _:
                return False
        if name not in {"typing.Annotated", "typing_extensions.Annotated"}:
            return False
        # Only annotation/type-alias positions; not runtime arguments containing Annotated.
        current = annotation
        parent = parents.get(current)
        containers = (ast.Subscript, ast.Tuple, ast.BinOp)
        while True:
            is_container = isinstance(parent, containers)
            if not is_container:
                break
            current = parent
            parent = parents.get(current)
        match parent:
            case ast.TypeAlias(value=value) if value is current:
                return True
            case ast.AnnAssign(annotation=value) if value is current:
                return True
            case ast.AnnAssign(value=value, annotation=marker) if value is current:
                name = self._declaration_name(marker)
                return name in {"typing.TypeAlias", "typing_extensions.TypeAlias"}
            case ast.arg(annotation=value) if value is current:
                return True
            case ast.FunctionDef(returns=value) | ast.AsyncFunctionDef(returns=value):
                return value is current
            case ast.Assign(value=value) if value is current:
                return True
        return False

    def _result_is_bound_or_discarded(self, node: ast.Call) -> bool:
        decorators = self.decorators
        if node in decorators:
            return True
        field_default = self._is_field_default(node)
        metadata = self._is_annotated_metadata(node)
        if field_default or metadata:
            return True
        parents = self.parents
        current: ast.AST = node
        parent = parents.get(current)
        match parent:
            case ast.Await(value=value) if value is current:
                current = parent
                parent = parents.get(current)
        match parent:
            case ast.Assign(value=value) | ast.AnnAssign(value=value):
                return value is current
            case ast.NamedExpr(value=value) | ast.Expr(value=value):
                return value is current
            case ast.Raise(exc=value):
                return value is node
        return False

    def _check_call(self, node: ast.Call) -> None:
        opening = self._opening(node)
        pairs = self.pairs
        closing = pairs[opening]
        tokens = self.tokens
        start_token, end_token = tokens[opening], tokens[closing]
        if start_token.start[0] != end_token.end[0]:
            self._report(node, "CS003", "Call arguments must be on one line; prepare multiline data in variables")
        allowed = self._result_is_bound_or_discarded(node)
        if not allowed:
            self._report(node, "CS004", "Bind the call result to a variable before consuming it")
        decorators = self.decorators
        if node in decorators:
            return
        match node.func:
            case ast.Attribute(value=ast.Attribute() | ast.Call()):
                self._report(node, "CS005", "Call target cannot be a chained attribute; bind its owner to a variable")

    def run(self) -> list[Diagnostic]:
        tree = self.tree
        nodes = ast.walk(tree)
        for node in nodes:
            match node:
                case ast.FunctionDef() | ast.AsyncFunctionDef():
                    self._check_definition(node)
                case ast.Call():
                    self._check_call(node)
        diagnostics = self.diagnostics
        diagnostics.sort()
        return diagnostics


def check_source(source: str, path: str = "<string>") -> list[Diagnostic]:
    """Return sorted diagnostics; syntax/tokenization failures are diagnostics too."""
    try:
        tree = ast.parse(source, filename=path)
        checker = StyleChecker(tree, source, path)
        diagnostics = checker.run()
    except (SyntaxError, tokenize.TokenError) as error:
        line = getattr(error, "lineno", None)
        line = line or 1
        message = str(error)
        issue = Diagnostic(path, line, "CS000", message)
        return [issue]
    return diagnostics


def check_file(path: Path) -> list[Diagnostic]:
    """Honor Python encoding cookies (including UTF-8 BOMs)."""
    filename = str(path)
    try:
        stream = tokenize.open(filename)
        with stream:
            source = stream.read()
    except (OSError, SyntaxError, UnicodeError) as error:
        message = str(error)
        issue = Diagnostic(filename, 1, "CS000", message)
        return [issue]
    diagnostics = check_source(source, filename)
    return diagnostics


def discover_files(paths: list[Path], excluded: frozenset[str]) -> tuple[list[Path], list[Diagnostic]]:
    files: set[Path] = set()
    diagnostics: list[Diagnostic] = []
    errors: list[OSError] = []
    for path in paths:
        ignored = any(part in excluded for part in path.parts)
        if ignored:
            continue
        exists = path.exists()
        if not exists:
            filename = str(path)
            issue = Diagnostic(filename, 1, "CS000", "Input path does not exist")
            diagnostics.append(issue)
            continue
        is_file = path.is_file()
        if is_file:
            if path.suffix == ".py":
                files.add(path)
            continue
        entries = os.walk(path, onerror=errors.append)
        for directory, subdirectories, filenames in entries:
            subdirectories[:] = [name for name in subdirectories if name not in excluded]
            root = Path(directory)
            for name in filenames:
                candidate = root / name
                if candidate.suffix == ".py":
                    files.add(candidate)
    for error in errors:
        filename = error.filename or "<filesystem>"
        message = str(error)
        issue = Diagnostic(filename, 1, "CS000", message)
        diagnostics.append(issue)
    ordered = sorted(files)
    return ordered, diagnostics


def default_paths() -> list[Path]:
    script = Path(__file__)
    script = script.resolve()
    scripts_directory = script.parent
    backend = scripts_directory.parent
    return [backend / name for name in DEFAULT_DIRECTORIES]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Python files or directories (default: backend/{src,tests,examples,scripts})")
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME", help="Additional directory basename to exclude (repeatable)")
    arguments = parser.parse_args(argv)
    paths = arguments.paths
    if not paths:
        paths = default_paths()
    additional_excludes = frozenset(arguments.exclude)
    excluded = EXCLUDED_DIRECTORIES | additional_excludes
    files, diagnostics = discover_files(paths, excluded)
    for path in files:
        issues = check_file(path)
        diagnostics.extend(issues)
    diagnostics.sort()
    for diagnostic in diagnostics:
        print(diagnostic)
    count = len(diagnostics)
    file_count = len(files)
    print(f"Checked {file_count} Python file(s); {count} violation(s).")
    if diagnostics:
        return 1
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
