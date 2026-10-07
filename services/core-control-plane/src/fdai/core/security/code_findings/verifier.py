"""Deterministic weakness verifiers that raise confidence to ``verified``.

For a supported weakness class and language, the verifier parses the fix-site file of the exact
acquired revision, finds a call to one of the class's catalog sinks on the fix-site line, and runs
an intra-procedural, flow-sensitive may-taint analysis over the enclosing function. The issue is
``verified`` only when the sink's dangerous argument is derived from an attacker-controlled source
(an entrypoint-decorated function parameter or a request attribute), no sanitizer or recognized
validation guard cuts the flow, and the sink is on a reachable path.

The analysis is deliberately conservative toward *not* verifying: validation guards remove taint
on both branches, calls to sanitizers cut taint, and unsupported constructs leave confidence where
the lanes put it. A verifier never lowers confidence, changes severity, or closes an issue. It
reads source files but never imports or executes them.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from fdai.core.security.code_findings.models import CodeSecurityIssue
from fdai.rule_catalog.code_security import Confidence
from fdai.rule_catalog.code_security_verifiers import (
    PythonVerifier,
    Sink,
    VerifierCatalog,
    VerifierClass,
)

_TERMINATING_CALLS = frozenset({"abort", "exit", "sys.exit", "os._exit"})
_MUTATORS = frozenset(
    {"append", "appendleft", "add", "extend", "extendleft", "insert", "setdefault", "update"}
)
_SAFE_CONVERTERS = re.compile(r"<(?:int|float|uuid):([A-Za-z_][A-Za-z0-9_]*)>")
_State = dict[str, str]


class VerifierOutcome(StrEnum):
    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class VerifierResult:
    issue_id: str
    outcome: VerifierOutcome
    reason: str
    verifier_version: str
    sink: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "verifier_version": self.verifier_version,
            "sink": self.sink,
            "source": self.source,
        }


def _aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                if name.asname:
                    aliases[name.asname] = name.name
                else:
                    root = name.name.split(".")[0]
                    aliases[root] = root
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for name in node.names:
                aliases[name.asname or name.name] = f"{node.module}.{name.name}"
    return aliases


def _raw(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _raw(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _terminal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _Module:
    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.aliases = _aliases(tree)

    def resolved(self, node: ast.expr) -> str | None:
        raw = _raw(node)
        if raw is None:
            return None
        head, _, rest = raw.partition(".")
        base = self.aliases.get(head, head)
        return f"{base}.{rest}" if rest else base

    def matches(self, node: ast.expr, entries: Iterable[str]) -> bool:
        resolved, terminal = self.resolved(node), _terminal(node)
        for entry in entries:
            if resolved == entry or ("." not in entry and terminal == entry):
                return True
        return False


def _sink_name(sink: Sink) -> str:
    return sink.call if sink.call is not None else f"*.{sink.method}"


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _is_sink(call: ast.Call, sink: Sink, module: _Module) -> bool:
    if sink.method is not None:
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == sink.method):
            return False
    elif module.resolved(call.func) != sink.call:
        return False
    for name, expected in sink.require_keyword.items():
        value = _keyword(call, name)
        if not (isinstance(value, ast.Constant) and value.value is expected):
            return False
    for name, safe in sink.unsafe_unless_keyword.items():
        value = _keyword(call, name)
        if value is None and len(call.args) > 1:
            value = call.args[1]
        if value is not None and _terminal(value) in safe:
            return False
    return len(call.args) > sink.arg


class _Taint:
    """Flow-sensitive may-taint over one function body toward one sink argument."""

    def __init__(
        self,
        module: _Module,
        config: PythonVerifier,
        weakness: VerifierClass,
        statement_of_sink: ast.stmt,
        sink_arg: ast.expr,
    ) -> None:
        self.module = module
        self.config = config
        self.sanitizers = (*config.global_sanitizers, *weakness.sanitizers)
        self.target = statement_of_sink
        self.sink_arg = sink_arg
        self.reached = False
        self.source: str | None = None
        self.validated: set[str] = set()

    def entry_state(self, function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> _State:
        state: _State = {}
        decorators = [] if function is None else function.decorator_list
        entry = [
            d
            for d in decorators
            if _terminal(d.func if isinstance(d, ast.Call) else d)
            in self.config.entrypoint_decorators
        ]
        if function is None or not entry:
            return state
        typed = {
            name
            for d in entry
            if isinstance(d, ast.Call)
            for arg in d.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            for name in _SAFE_CONVERTERS.findall(arg.value)
        }
        arguments = function.args
        params = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        params += [item for item in (arguments.vararg, arguments.kwarg) if item is not None]
        for param in params:
            if param.arg in self.config.ignored_parameters or param.arg in typed:
                continue
            annotation = param.annotation
            if annotation is not None and self.module.matches(
                annotation, self.config.safe_parameter_annotations
            ):
                continue
            state[param.arg] = (
                f"parameter {param.arg} of entrypoint {function.name} (line {param.lineno})"
            )
        return state

    def _request(self, node: ast.Attribute) -> bool:
        if node.attr not in self.config.request_attributes:
            return False
        raw = _raw(node.value)
        resolved = self.module.resolved(node.value)
        return raw in self.config.request_roots or (
            resolved is not None and resolved.rsplit(".", 1)[-1] == "request"
        )

    def taint(self, node: ast.expr | None, state: _State) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Attribute | ast.Subscript | ast.Call) and (
            ast.dump(node) in self.validated
        ):
            return None
        if isinstance(node, ast.Name):
            return state.get(node.id)
        if isinstance(node, ast.Attribute):
            if self._request(node):
                return f"request attribute {_raw(node)} (line {node.lineno})"
            if self.module.matches(node, self.config.source_attributes):
                return f"source {_raw(node)} (line {node.lineno})"
            return self.taint(node.value, state)
        if isinstance(node, ast.Call):
            if self.module.matches(node.func, self.sanitizers):
                return None
            if self.module.matches(node.func, self.config.source_calls):
                return f"source call {_raw(node.func)} (line {node.lineno})"
            arguments = self._first([*node.args, *(kw.value for kw in node.keywords)], state)
            if isinstance(node.func, ast.Attribute):
                if arguments and node.func.attr in _MUTATORS:
                    self._assign(node.func.value, arguments, state, mutation=True)
                return self.taint(node.func, state) or arguments
            return arguments
        if isinstance(node, ast.NamedExpr):
            label = self.taint(node.value, state)
            self._assign(node.target, label, state)
            return label
        if isinstance(node, ast.Compare | ast.Lambda | ast.Constant):
            return None
        if isinstance(node, ast.Dict):
            return self._first([*node.keys, *node.values], state)
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            return self._first([*(g.iter for g in node.generators), node.elt], state)
        if isinstance(node, ast.DictComp):
            return self._first([*(g.iter for g in node.generators), node.value], state)
        return self._first(
            [child for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr)], state
        )

    def _first(self, nodes: Sequence[ast.expr | None], state: _State) -> str | None:
        for node in nodes:
            label = self.taint(node, state)
            if label:
                return label
        return None

    def _assign(
        self, target: ast.expr, label: str | None, state: _State, *, mutation: bool = False
    ) -> None:
        """Bind ``label`` to the assigned names; mutating a container taints its base name."""
        if isinstance(target, ast.Name) and not mutation:
            if label:
                state[target.id] = label
            else:
                state.pop(target.id, None)
        elif isinstance(target, ast.Tuple | ast.List) and not mutation:
            for element in target.elts:
                self._assign(element, label, state)
        elif isinstance(target, ast.Starred) and not mutation:
            self._assign(target.value, label, state)
        elif label:
            base: ast.expr = target
            while isinstance(base, ast.Attribute | ast.Subscript):
                base = base.value
            if isinstance(base, ast.Name):
                state[base.id] = label

    def _validated(self, test: ast.expr, state: _State) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(test):
            checked: list[ast.expr] = []
            if isinstance(node, ast.Compare) and any(
                isinstance(op, ast.In | ast.NotIn) for op in node.ops
            ):
                checked.append(node.left)
            elif isinstance(node, ast.Call) and _terminal(node.func) in self.config.validators:
                checked.extend(node.args)
                if isinstance(node.func, ast.Attribute):
                    checked.append(node.func.value)
            for expr in checked:
                self.validated.update(
                    ast.dump(sub)
                    for sub in ast.walk(expr)
                    if isinstance(sub, ast.Attribute | ast.Subscript | ast.Call)
                )
                names.update(
                    sub.id
                    for sub in ast.walk(expr)
                    if isinstance(sub, ast.Name) and sub.id in state
                )
        return names

    def _check(self, state: _State) -> None:
        self.reached = True
        label = self.taint(self.sink_arg, state)
        if label and self.source is None:
            self.source = label

    @staticmethod
    def _merge(*states: _State | None) -> _State | None:
        live = [state for state in states if state is not None]
        if not live:
            return None
        merged: _State = {}
        for state in live:
            for name, label in state.items():
                merged.setdefault(name, label)
        return merged

    def block(self, statements: Sequence[ast.stmt], state: _State | None) -> _State | None:
        for statement in statements:
            if state is None:
                return None
            state = self.statement(statement, dict(state))
        return state

    def statement(self, node: ast.stmt, state: _State) -> _State | None:  # noqa: PLR0911, PLR0912
        if node is self.target:
            self._check(state)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return state
        if isinstance(node, ast.Assign):
            label = self.taint(node.value, state)
            for target in node.targets:
                self._assign(target, label, state)
            return state
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self._assign(node.target, self.taint(node.value, state), state)
            return state
        if isinstance(node, ast.AugAssign):
            label = self.taint(node.target, state) or self.taint(node.value, state)
            self._assign(node.target, label, state)
            return state
        if isinstance(node, ast.Return | ast.Raise | ast.Continue | ast.Break):
            return None
        if isinstance(node, ast.Expr):
            self.taint(node.value, state)
            call = node.value
            if isinstance(call, ast.Call) and self.module.matches(call.func, _TERMINATING_CALLS):
                return None
            return state
        if isinstance(node, ast.If):
            validated = self._validated(node.test, state)
            for name in validated:
                state.pop(name, None)
            if isinstance(node.test, ast.Constant):
                branch = node.body if node.test.value else node.orelse
                return self.block(branch, state)
            return self._merge(self.block(node.body, state), self.block(node.orelse, state))
        if isinstance(node, ast.For | ast.AsyncFor):
            self._assign(node.target, self.taint(node.iter, state), state)
            first = self.block(node.body, state)
            second = self.block(node.body, self._merge(state, first))
            return self.block(node.orelse, self._merge(state, first, second))
        if isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and not node.test.value:
                return self.block(node.orelse, state)
            first = self.block(node.body, state)
            second = self.block(node.body, self._merge(state, first))
            return self.block(node.orelse, self._merge(state, first, second))
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars is not None:
                    self._assign(item.optional_vars, self.taint(item.context_expr, state), state)
            return self.block(node.body, state)
        if isinstance(node, ast.Try | ast.TryStar):
            body = self.block(node.body, state)
            entry = self._merge(state, body)
            handlers = [self.block(handler.body, entry) for handler in node.handlers]
            result = self._merge(self.block(node.orelse, body), *handlers)
            if node.finalbody:
                return self.block(node.finalbody, result if result is not None else entry)
            return result
        if isinstance(node, ast.Match):
            return self._merge(*(self.block(case.body, state) for case in node.cases))
        return state


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _owner(
    tree: ast.Module, parents: Mapping[int, ast.AST], call: ast.Call
) -> tuple[ast.stmt, ast.FunctionDef | ast.AsyncFunctionDef | None, Sequence[ast.stmt]]:
    """Return the innermost statement holding the call and its enclosing function body."""
    node: ast.AST = call
    while not isinstance(node, ast.stmt):
        node = parents[id(node)]
    statement = node
    while id(node) in parents:
        node = parents[id(node)]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return statement, node, node.body
    return statement, None, tree.body


def _verify_python(
    issue: CodeSecurityIssue,
    source: bytes,
    config: PythonVerifier,
    weakness: VerifierClass,
    version: str,
) -> VerifierResult:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return VerifierResult(issue.issue_id, VerifierOutcome.UNSUPPORTED, "parse_error", version)
    module = _Module(tree)
    line = issue.fix_site.start_line or 0
    parents = _parents(tree)
    found_sink: str | None = None
    reached_any = False
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if not call.lineno <= line <= (call.end_lineno or call.lineno):
            continue
        for sink in weakness.sinks:
            if not _is_sink(call, sink, module):
                continue
            found_sink = found_sink or _sink_name(sink)
            target, function, body = _owner(tree, parents, call)
            analysis = _Taint(module, config, weakness, target, call.args[sink.arg])
            analysis.block(body, analysis.entry_state(function))
            reached_any = reached_any or analysis.reached
            if analysis.reached and analysis.source:
                return VerifierResult(
                    issue.issue_id,
                    VerifierOutcome.VERIFIED,
                    "attacker_controlled_flow",
                    version,
                    sink=_sink_name(sink),
                    source=analysis.source,
                )
    if found_sink is None:
        reason = "no_sink_at_fix_site"
    elif not reached_any:
        reason = "unreachable"
    else:
        reason = "argument_not_attacker_controlled"
    return VerifierResult(
        issue.issue_id, VerifierOutcome.NOT_VERIFIED, reason, version, sink=found_sink
    )


def verify_issues(
    root: Path,
    issues: Sequence[CodeSecurityIssue],
    catalog: VerifierCatalog,
    *,
    revision: str,
) -> tuple[VerifierResult, ...]:
    """Run the catalog verifiers for every supported issue against one acquired tree."""
    base = root.resolve()
    version = f"{catalog.catalog_id}@{catalog.version}"
    results: list[VerifierResult] = []
    for index, issue in enumerate(issues):

        def unsupported(reason: str, issue: CodeSecurityIssue = issue) -> VerifierResult:
            return VerifierResult(issue.issue_id, VerifierOutcome.UNSUPPORTED, reason, version)

        if index >= catalog.limits.max_issues:
            results.append(unsupported("issue_limit"))
            continue
        if issue.revision != revision:
            results.append(unsupported("revision_mismatch"))
            continue
        weakness = catalog.python.classes.get(issue.weakness_class)
        if weakness is None:
            results.append(unsupported("unsupported_class"))
            continue
        if not issue.fix_site.path.endswith(".py") or not issue.fix_site.start_line:
            results.append(unsupported("unsupported_language"))
            continue
        path = base / issue.fix_site.path
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            results.append(unsupported("file_unavailable"))
            continue
        if path.is_symlink() or not resolved.is_relative_to(base) or not resolved.is_file():
            results.append(unsupported("file_unavailable"))
            continue
        if resolved.stat().st_size > catalog.limits.max_file_bytes:
            results.append(unsupported("file_too_large"))
            continue
        results.append(
            _verify_python(issue, resolved.read_bytes(), catalog.python, weakness, version)
        )
    return tuple(results)


def verified_confidence(results: Iterable[VerifierResult]) -> Mapping[str, Confidence]:
    """Return the ``AnalysisContext.verifications`` entries for verified issues."""
    return {
        result.issue_id: Confidence.VERIFIED
        for result in results
        if result.outcome is VerifierOutcome.VERIFIED
    }


__all__ = [
    "VerifierOutcome",
    "VerifierResult",
    "verified_confidence",
    "verify_issues",
]
