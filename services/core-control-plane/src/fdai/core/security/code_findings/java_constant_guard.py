"""Veto Java SQL verifier evidence only for provably constant sink arguments.

This is a bounded expression/definition slice, not a Java compiler or general taint analyzer.
Unsupported syntax, mutation, dispatch, or path selection leaves the engine result unchanged.
Source is parsed, never rewritten, imported, compiled, or executed.
"""

from __future__ import annotations

import hashlib
import warnings
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from fdai.core.security.code_findings.java_constant_values import (
    Constant,
    binary,
    coerce,
    literal,
    unary,
)

VERSION = "fdai.java.constant-guard@1"
_SINKS = frozenset(
    {
        "execute",
        "executeQuery",
        "executeUpdate",
        "prepareStatement",
        "query",
        "queryForList",
        "update",
        "createQuery",
        "createNativeQuery",
    }
)
_LANGUAGE = Language(tree_sitter_java.language())


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _parent(node: Node, kind: str) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type == kind:
            return parent
        parent = parent.parent
    return None


def _contains(container: Node, node: Node) -> bool:
    return container.start_byte <= node.start_byte and node.end_byte <= container.end_byte


def _field(node: Node | None, name: str) -> Node | None:
    return node.child_by_field_name(name) if node is not None else None


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


class _Slice:
    def __init__(self, source: bytes) -> None:
        # The locked 0.25 parser supports this bound for byte input. Its replacement progress
        # callback only supports callable input; never leave untrusted byte parsing unbounded.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            parser = Parser(_LANGUAGE, timeout_micros=100_000)
        self.tree = parser.parse(source)
        self.nodes = tuple(islice(_walk(self.tree.root_node), 25001))
        self.budget = 10000
        self.active: set[tuple[int, str]] = set()

    def expression(
        self, node: Node | None, parameters: dict[str, Constant | None], depth: int = 0
    ) -> Constant | None:
        self.budget -= 1
        if node is None or depth > 32 or self.budget <= 0:
            return None
        key = (node.id, repr(parameters))
        if key in self.active:
            return None
        self.active.add(key)
        try:
            return self._expression(node, parameters, depth + 1)
        finally:
            self.active.remove(key)

    def _expression(
        self, node: Node, parameters: dict[str, Constant | None], depth: int
    ) -> Constant | None:
        if node.type == "identifier":
            return self._local(node, parameters, depth)
        if node.type == "parenthesized_expression":
            return self.expression(node.named_children[0], parameters, depth)
        if node.type == "binary_expression":
            left = self.expression(_field(node, "left"), parameters, depth)
            operator = _text(_field(node, "operator"))
            if (
                left is not None
                and left.kind == "boolean"
                and ((operator == "&&" and not left.value) or (operator == "||" and left.value))
            ):
                return left
            return binary(operator, left, self.expression(_field(node, "right"), parameters, depth))
        if node.type == "unary_expression":
            return unary(
                _text(_field(node, "operator")),
                self.expression(_field(node, "operand"), parameters, depth),
            )
        if node.type == "ternary_expression":
            condition = self.expression(_field(node, "condition"), parameters, depth)
            if condition is not None and condition.kind == "boolean":
                return self.expression(
                    _field(node, "consequence" if condition.value else "alternative"),
                    parameters,
                    depth,
                )
            return None
        if node.type == "method_invocation":
            return self._call(node, parameters, depth)
        return literal(_text(node), node.type)

    def _local(
        self, node: Node, parameters: dict[str, Constant | None], depth: int
    ) -> Constant | None:
        method = _parent(node, "method_declaration")
        if method is None:
            return None
        name = _text(node)
        members = [n for n in self.nodes if _parent(n, "method_declaration") == method]
        writes = [
            n
            for n in members
            if n.start_byte < node.start_byte
            and (
                (n.type == "assignment_expression" and _text(_field(n, "left")) == name)
                or (
                    n.type == "update_expression"
                    and any(_text(c) == name for c in n.named_children)
                )
            )
        ]
        declarations = [
            n
            for n in members
            if n.type == "variable_declarator"
            and _text(_field(n, "name")) == name
            and n.start_byte < node.start_byte
            and (scope := _parent(n, "block")) is not None
            and _contains(scope, node)
        ]
        if not declarations:
            return parameters.get(name) if not writes else None
        if len(declarations) != 1:
            return None
        declaration = declarations[0]
        definitions = (
            [(declaration, _field(declaration, "value"))]
            if _field(declaration, "value") is not None
            else []
        )
        for write in writes:
            if write.type != "assignment_expression" or _text(_field(write, "operator")) != "=":
                if self.reachable(write, parameters, depth) is not False:
                    return None
                continue
            definitions.append((write, _field(write, "right")))
        possible = [
            (binding, value, self.reachable(binding, parameters, depth))
            for binding, value in definitions
        ]
        possible = [entry for entry in possible if entry[2] is not False]
        if len(possible) != 1 or possible[0][2] is not True:
            return None
        declared_type = _text(_field(declaration.parent, "type"))
        return coerce(self.expression(possible[0][1], parameters, depth), declared_type)

    def reachable(
        self, node: Node, parameters: dict[str, Constant | None], depth: int
    ) -> bool | None:
        child, parent = node, node.parent
        certainty: bool | None = True
        while parent is not None and parent.type != "method_declaration":
            if parent.type in {
                "while_statement",
                "for_statement",
                "enhanced_for_statement",
                "do_statement",
                "catch_clause",
                "lambda_expression",
                "switch_rule",
            }:
                certainty = None
            if parent.type == "if_statement":
                condition = self.expression(_field(parent, "condition"), parameters, depth)
                if condition is None or condition.kind != "boolean":
                    certainty = None
                else:
                    branch = _field(parent, "consequence" if condition.value else "alternative")
                    if branch is None or not _contains(branch, node):
                        return False
            if parent.type == "switch_block_statement_group":
                switch = _parent(parent, "switch_expression")
                selected = (
                    self._switch_groups(switch, parameters, depth) if switch is not None else None
                )
                if selected is None:
                    certainty = None
                elif parent not in selected:
                    return False
            if parent.type in {"block", "switch_block_statement_group"}:
                for previous in parent.named_children:
                    if previous.end_byte > child.start_byte:
                        break
                    if (
                        parent.type == "switch_block_statement_group"
                        and previous.type == "break_statement"
                    ):
                        return False
                    if self._exits(previous, parameters, depth):
                        return False
            if parent.type == "try_statement":
                certainty = None
            child, parent = parent, parent.parent
        return certainty

    def _exits(self, node: Node, parameters: dict[str, Constant | None], depth: int) -> bool:
        if depth > 32 or self.budget <= 0:
            return False
        if node.type in {"return_statement", "throw_statement"}:
            return True
        if node.type == "block":
            return any(self._exits(c, parameters, depth + 1) for c in node.named_children)
        if node.type == "if_statement":
            condition = self.expression(_field(node, "condition"), parameters, depth)
            if condition is not None and condition.kind == "boolean":
                branch = _field(node, "consequence" if condition.value else "alternative")
                return branch is not None and self._exits(branch, parameters, depth + 1)
            a, b = _field(node, "consequence"), _field(node, "alternative")
            return (
                a is not None
                and b is not None
                and self._exits(a, parameters, depth + 1)
                and self._exits(b, parameters, depth + 1)
            )
        return False

    def _switch_groups(
        self, switch: Node, parameters: dict[str, Constant | None], depth: int
    ) -> list[Node] | None:
        value = self.expression(_field(switch, "condition"), parameters, depth)
        body = _field(switch, "body")
        if value is None or body is None:
            return None
        groups = body.named_children
        selected = default = None
        for index, group in enumerate(groups):
            if group.type != "switch_block_statement_group":
                return None
            for label in (n for n in group.named_children if n.type == "switch_label"):
                if _text(label) == "default":
                    default = index
                elif len(label.named_children) == 1:
                    candidate = self.expression(label.named_children[0], parameters, depth)
                    if candidate is None:
                        return None
                    if candidate == value or binary("==", candidate, value) == Constant(
                        "boolean", True
                    ):
                        selected = index
                else:
                    return None
        selected = default if selected is None else selected
        if selected is None:
            return []
        active = []
        for group in groups[selected:]:
            active.append(group)
            for statement in group.named_children:
                if statement.type in {"break_statement", "return_statement", "throw_statement"}:
                    return active
                if any(
                    n.type in {"break_statement", "return_statement", "throw_statement"}
                    for n in _walk(statement)
                ):
                    return None
        return active

    def _call(
        self, node: Node, parameters: dict[str, Constant | None], depth: int
    ) -> Constant | None:
        receiver, name, arguments = (
            _field(node, "object"),
            _text(_field(node, "name")),
            _field(node, "arguments"),
        )
        if arguments is None:
            return None
        if len(arguments.named_children) > 32:
            return None
        args = [self.expression(n, parameters, depth) for n in arguments.named_children]
        if name in {"charAt", "length"} and receiver is not None:
            value = self.expression(receiver, parameters, depth)
            if value is not None and value.kind == "String" and isinstance(value.value, str):
                # Python indices and lengths differ for supplementary UTF-16 characters.
                if any(ord(c) > 0xFFFF for c in value.value):
                    return None
                if name == "length" and not args:
                    return Constant("int", len(value.value))
                if (
                    name == "charAt"
                    and len(args) == 1
                    and args[0] is not None
                    and args[0].kind == "int"
                    and isinstance(args[0].value, int)
                    and 0 <= args[0].value < len(value.value)
                ):
                    return Constant("char", value.value[args[0].value])
            return None
        owner = _parent(node, "class_declaration")
        exact_new = receiver is not None and receiver.type == "object_creation_expression"
        if exact_new and receiver is not None:
            creation_args = _field(receiver, "arguments")
            if (
                creation_args is None
                or creation_args.named_children
                or any(
                    c.type not in {"type_identifier", "argument_list"}
                    for c in receiver.named_children
                )
            ):
                return None
            classes = [
                c
                for c in self.nodes
                if c.type == "class_declaration"
                and _text(_field(c, "name")) == _text(_field(receiver, "type"))
                and _parent(c, "class_declaration") == owner
            ]
            if len(classes) != 1:
                return None
            owner = classes[0]
            body = _field(owner, "body")
            if (
                body is None
                or _field(owner, "superclass") is not None
                or _field(owner, "interfaces") is not None
                or any(
                    c.type not in {"method_declaration", "comment", "line_comment", "block_comment"}
                    for c in body.named_children
                )
            ):
                return None
        elif receiver is not None:
            if (
                owner is None
                or receiver.type != "identifier"
                or _text(receiver) != _text(_field(owner, "name"))
                or _field(owner, "superclass") is not None
                or _field(owner, "interfaces") is not None
            ):
                return None
            caller = _parent(node, "method_declaration")
            if caller is None or any(
                n.type in {"variable_declarator", "formal_parameter"}
                and _text(_field(n, "name")) == _text(receiver)
                for n in _walk(caller)
            ):
                return None
            if any(
                n.type == "variable_declarator"
                and _parent(n, "field_declaration") is not None
                and _text(_field(n, "name")) == _text(receiver)
                for n in self.nodes
            ):
                return None
        if owner is None:
            return None
        methods = [
            m
            for m in self.nodes
            if m.type == "method_declaration"
            and _parent(m, "class_declaration") == owner
            and _text(_field(m, "name")) == name
        ]
        if len(methods) != 1:
            return None
        method = methods[0]
        modifiers = next(
            (set(_text(c).split()) for c in method.named_children if c.type == "modifiers"), set()
        )
        if not exact_new and not {"private", "static"} <= modifiers:
            return None
        formal = _field(method, "parameters")
        body = _field(method, "body")
        if formal is None or body is None or len(formal.named_children) != len(args):
            return None
        bindings = {
            _text(_field(p, "name")): coerce(a, _text(_field(p, "type")))
            for p, a in zip(formal.named_children, args, strict=True)
        }
        locals_in_body = [n for n in _walk(body) if n.type == "variable_declarator"]
        for member in _walk(body):
            if member.type in {
                "try_statement",
                "while_statement",
                "for_statement",
                "enhanced_for_statement",
                "do_statement",
                "synchronized_statement",
                "throw_statement",
                "update_expression",
                "object_creation_expression",
                "class_declaration",
                "lambda_expression",
                "field_access",
                "array_access",
            }:
                return None
            if member.type == "method_invocation":
                known_receiver = self.expression(_field(member, "object"), bindings, depth)
                if (
                    _text(_field(member, "name")) not in {"charAt", "length"}
                    or known_receiver is None
                    or known_receiver.kind != "String"
                ):
                    return None
            left = _field(member, "left")
            if member.type == "assignment_expression":
                if (
                    left is None
                    or left.type != "identifier"
                    or _text(_field(member, "operator")) != "="
                ):
                    return None
            if member.type == "assignment_expression" and not any(
                _text(_field(declaration, "name")) == _text(left)
                and declaration.start_byte < member.start_byte
                and (scope := _parent(declaration, "block")) is not None
                and _contains(scope, member)
                for declaration in locals_in_body
            ):
                return None
        returns = [
            r
            for r in _walk(body)
            if r.type == "return_statement" and self.reachable(r, bindings, depth) is not False
        ]
        values = [
            self.expression(r.named_children[0], bindings, depth) if r.named_children else None
            for r in returns
        ]
        if not values or values[0] is None or any(v != values[0] for v in values):
            return None
        if not body.named_children or not self._exits(body.named_children[-1], bindings, depth):
            return None
        return coerce(values[0], _text(_field(method, "type")))


def java_sql_constant_veto(
    repository: Path, relative_path: str, line: int, *, max_file_bytes: int = 1_000_000
) -> str | None:
    """Return a source-bound constant proof, or ``None`` to keep the engine evidence.

    A proof requires every SQL argument that could match the hit's line to be constant.
    Missing, escaping, oversized, malformed, or unsupported source never creates a veto.
    """
    root = repository.resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        return None
    try:
        if path.stat().st_size > max_file_bytes:
            return None
        with path.open("rb") as stream:
            source = stream.read(max_file_bytes + 1)
    except OSError:
        return None
    if len(source) > max_file_bytes or b"\\u" in source:
        # Java expands Unicode escapes before lexing, including escapes inside comments.
        # Tree-sitter sees the unexpanded source; don't prove constants under different lexing.
        return None
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        analysis = _Slice(source)
    except ValueError:
        # The parser reports its deadline as parsing failure. No constant proof is available.
        return None
    if analysis.tree.root_node.has_error or len(analysis.nodes) > 25000:
        return None
    candidates = []
    for node in analysis.nodes:
        if node.type != "method_invocation" or _text(_field(node, "name")) not in _SINKS:
            continue
        args = _field(node, "arguments")
        if args is not None and args.named_children:
            arg = args.named_children[0]
            if arg.start_point.row + 1 <= line <= arg.end_point.row + 1:
                parent = arg.parent
                while parent is not None and parent.type != "method_declaration":
                    if parent.type in {
                        "while_statement",
                        "for_statement",
                        "enhanced_for_statement",
                        "do_statement",
                        "lambda_expression",
                    }:
                        # A write after this textual sink may reach its next iteration.
                        return None
                    parent = parent.parent
                candidates.append(arg)
    if not candidates or any(analysis.expression(arg, {}) is None for arg in candidates):
        return None
    return f"{VERSION}; source_sha256={hashlib.sha256(source).hexdigest()}; line={line}"
