"""Resolve bounded Java external string constants without leaving the source root."""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterator, Mapping
from itertools import islice
from pathlib import Path

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from fdai.core.security.code_findings.java_constant_values import Constant, binary, literal

_QUALIFIED_CONSTANT = re.compile(
    rb"\b(?P<class>(?:[a-z_][A-Za-z0-9_]*\.)+[A-Z][A-Za-z0-9_]*)"
    rb"\.(?P<field>[A-Z][A-Z0-9_]*)\b"
)
_LANGUAGE = Language(tree_sitter_java.language())


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _field(node: Node | None, name: str) -> Node | None:
    return node.child_by_field_name(name) if node is not None else None


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


def _static_string(node: Node | None, constants: Mapping[str, Constant]) -> Constant | None:
    if node is None:
        return None
    if node.type == "identifier":
        return constants.get(_text(node))
    if node.type == "parenthesized_expression":
        return _static_string(node.named_children[0], constants)
    if node.type == "binary_expression":
        return binary(
            _text(_field(node, "operator")),
            _static_string(_field(node, "left"), constants),
            _static_string(_field(node, "right"), constants),
        )
    if node.type in {"field_access", "scoped_identifier"} and _text(node) in {
        "File.separator",
        "java.io.File.separator",
    }:
        return Constant("String", "<file-separator>")
    if node.type == "method_invocation":
        receiver = _text(_field(node, "object"))
        arguments = _field(node, "arguments")
        if (
            receiver in {"System", "java.lang.System"}
            and _text(_field(node, "name")) == "getProperty"
            and arguments is not None
            and len(arguments.named_children) == 1
        ):
            key = _static_string(arguments.named_children[0], constants)
            if key is not None and key.kind == "String":
                return Constant("String", f"<system-property:{key.value}>")
    return literal(_text(node), node.type)


def qualified_string_constants(
    root: Path, source: bytes, *, max_file_bytes: int = 1_000_000
) -> Mapping[str, Constant]:
    """Return exact qualified constants proven from unique regular source files."""
    resolved: dict[str, Constant] = {}
    for match in _QUALIFIED_CONSTANT.finditer(source):
        class_name = match.group("class").decode("ascii")
        field_name = match.group("field").decode("ascii")
        reference = f"{class_name}.{field_name}"
        if reference in resolved:
            continue
        package_name, _, simple_name = class_name.rpartition(".")
        candidates = tuple(islice(root.rglob(f"{simple_name}.java"), 2))
        if len(candidates) != 1:
            continue
        candidate_path = candidates[0]
        try:
            resolved_path = candidate_path.resolve(strict=True)
            if (
                candidate_path.is_symlink()
                or not resolved_path.is_relative_to(root)
                or resolved_path.stat().st_size > max_file_bytes
            ):
                continue
            candidate_source = resolved_path.read_bytes()
        except OSError:
            continue
        if len(candidate_source) > max_file_bytes:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            parser = Parser(_LANGUAGE, timeout_micros=100_000)
        tree = parser.parse(candidate_source)
        nodes = tuple(islice(_walk(tree.root_node), 25_001))
        if tree.root_node.has_error or len(nodes) > 25_000:
            continue
        if [_text(node) for node in nodes if node.type == "package_declaration"] != [
            f"package {package_name};"
        ]:
            continue
        constants: dict[str, Constant] = {}
        for node in nodes:
            if node.type != "field_declaration":
                continue
            declaration_text = _text(node)
            if (
                "static" not in declaration_text.split()
                or "final" not in declaration_text.split()
                or _text(_field(node, "type")) != "String"
            ):
                continue
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name = _text(_field(declarator, "name"))
                value = _static_string(_field(declarator, "value"), constants)
                if value is not None and value.kind == "String":
                    constants[name] = value
        if (value := constants.get(field_name)) is not None:
            resolved[reference] = value
    return resolved


__all__ = ["qualified_string_constants"]
