"""Bounded Python interprocedural taint analysis for code security."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.analysis_contracts import (
    CodeGraphArtifact,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    GraphEdgeKind,
    GraphNodeKind,
    PathEvidence,
    PathEvidenceStep,
    PathStepRole,
    RuleAnalysisKind,
    RuleSelector,
    SourceSpan,
)
from fdai.core.security.code_findings.python_graph import (
    FRONTEND,
    VERSION,
    PythonAnalysisLimits,
    PythonFunction,
    PythonGraphIndex,
    add_edge,
    build_python_graph_index,
    coverage_limit,
    resolve_call,
    resolved_name,
    source_span,
    stable_id,
)


@dataclass(frozen=True, slots=True)
class PythonAnalysisResult:
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]


@dataclass(frozen=True, slots=True)
class _TracePoint:
    node_id: str
    role: PathStepRole
    span: SourceSpan
    context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Taint:
    trace: tuple[_TracePoint, ...]


@dataclass(slots=True)
class _ReturnState:
    value: _Taint | None = None


class _Analyzer:
    def __init__(
        self, index: PythonGraphIndex, rule: CodeSecurityRuleSpec, limits: PythonAnalysisLimits
    ) -> None:
        self.index = index
        self.limits = limits
        self.sources = tuple(selector for selector in rule.selectors if selector.role == "source")
        self.sinks = tuple(selector for selector in rule.selectors if selector.role == "sink")
        self.propagators = tuple(
            selector for selector in rule.selectors if selector.role == "propagator"
        )
        self.sanitizers = tuple(
            selector for selector in rule.selectors if selector.role == "sanitizer"
        )
        self.active: set[tuple[str, tuple[bool, ...]]] = set()
        self.contexts = 0
        self.candidates: list[tuple[_TracePoint, ...]] = []

    @staticmethod
    def _matches(name: str | None, selector: RuleSelector) -> bool:
        return bool(
            name
            and (
                name == selector.symbol
                or name.startswith(f"{selector.symbol}.")
                or ("." not in selector.symbol and name.rsplit(".", 1)[-1] == selector.symbol)
            )
        )

    def _source(
        self, node: ast.AST, function: PythonFunction, context: tuple[str, ...]
    ) -> _Taint | None:
        target = node.func if isinstance(node, ast.Call) else node
        name = resolved_name(target, function.module)
        if not any(self._matches(name, selector) for selector in self.sources):
            return None
        location = source_span(function.module.path, node)
        node_id = stable_id(
            "source", function.module.path, location.start_line, location.start_column, name
        )
        self.index.nodes.setdefault(
            node_id,
            CodeGraphNode(
                node_id=node_id,
                kind=GraphNodeKind.SOURCE,
                name=name or "source",
                span=location,
            ),
        )
        return _Taint((_TracePoint(node_id, PathStepRole.SOURCE, location, context),))

    @staticmethod
    def _first(values: Iterable[_Taint | None]) -> _Taint | None:
        return next((value for value in values if value is not None), None)

    def _expression(
        self,
        node: ast.expr | None,
        function: PythonFunction,
        state: Mapping[str, _Taint],
        context: tuple[str, ...],
        depth: int,
    ) -> _Taint | None:
        if node is None:
            return None
        direct = self._source(node, function, context)
        if direct:
            return direct
        if isinstance(node, ast.Name):
            return state.get(node.id)
        if isinstance(node, ast.Constant | ast.Lambda):
            return None
        if isinstance(node, ast.Call):
            return self._call(node, function, state, context, depth)
        if isinstance(node, ast.Attribute | ast.Subscript):
            return self._expression(node.value, function, state, context, depth)
        return self._first(
            self._expression(child, function, state, context, depth)
            for child in ast.iter_child_nodes(node)
            if isinstance(child, ast.expr)
        )

    def _sink(
        self,
        call: ast.Call,
        function: PythonFunction,
        context: tuple[str, ...],
        name: str | None,
        argument: _Taint | None,
    ) -> None:
        if argument is None:
            return
        if len(self.candidates) >= self.limits.max_paths:
            self.index.coverage.add(coverage_limit("path-limit", len(self.candidates)))
            return
        location = source_span(function.module.path, call)
        sink_id = stable_id(
            "sink", function.module.path, location.start_line, location.start_column, name
        )
        self.index.nodes.setdefault(
            sink_id,
            CodeGraphNode(
                node_id=sink_id,
                kind=GraphNodeKind.SINK,
                name=name or "sink",
                span=location,
            ),
        )
        point = _TracePoint(sink_id, PathStepRole.SINK, location, context)
        self.candidates.append((*argument.trace, point))

    def _call(
        self,
        call: ast.Call,
        function: PythonFunction,
        state: Mapping[str, _Taint],
        context: tuple[str, ...],
        depth: int,
    ) -> _Taint | None:
        name = resolved_name(call.func, function.module)
        arguments = [
            self._expression(argument, function, state, context, depth) for argument in call.args
        ]
        receiver = (
            self._expression(call.func.value, function, state, context, depth)
            if isinstance(call.func, ast.Attribute)
            else None
        )
        sanitizer = next(
            (selector for selector in self.sanitizers if self._matches(name, selector)), None
        )
        sink = next((selector for selector in self.sinks if self._matches(name, selector)), None)
        if sink is not None:
            argument_index = sink.argument_index or 0
            argument = arguments[argument_index] if len(arguments) > argument_index else None
            self._sink(call, function, context, name, argument)
            return None
        if sanitizer is not None:
            return None
        target = resolve_call(call, function, self.index)
        if target is None:
            taint = self._first((receiver, *arguments))
            declared = any(self._matches(name, selector) for selector in self.propagators)
            if taint is not None and not declared and name not in {"str", "repr", "format"}:
                self.index.coverage.add(
                    coverage_limit("unresolved-call", function.module.path, call.lineno, name)
                )
            return taint
        call_id = stable_id("call", function.module.path, call.lineno, call.col_offset)
        nested_context = (*context, target.function_id)
        call_point = _TracePoint(
            call_id, PathStepRole.CALL, source_span(function.module.path, call), nested_context
        )
        passed = {
            parameter: _Taint((*argument.trace, call_point))
            for parameter, argument in zip(target.parameters, arguments, strict=False)
            if argument is not None
        }
        returned = self._function(target, passed, nested_context, depth + 1)
        if returned is None:
            return None
        return_point = _TracePoint(
            call_id, PathStepRole.RETURN, source_span(function.module.path, call), nested_context
        )
        return _Taint((*returned.trace, return_point))

    def _assign(self, target: ast.expr, value: _Taint | None, state: dict[str, _Taint]) -> None:
        if isinstance(target, ast.Name):
            if value is None:
                state.pop(target.id, None)
            else:
                state[target.id] = value
        elif isinstance(target, ast.Tuple | ast.List):
            for item in target.elts:
                self._assign(item, value, state)

    def _block(
        self,
        statements: Sequence[ast.stmt],
        function: PythonFunction,
        state: dict[str, _Taint],
        context: tuple[str, ...],
        depth: int,
        returned: _ReturnState,
    ) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign):
                value = self._expression(statement.value, function, state, context, depth)
                for target in statement.targets:
                    self._assign(target, value, state)
            elif isinstance(statement, ast.AnnAssign):
                self._assign(
                    statement.target,
                    self._expression(statement.value, function, state, context, depth),
                    state,
                )
            elif isinstance(statement, ast.AugAssign):
                value = self._first(
                    (
                        self._expression(statement.target, function, state, context, depth),
                        self._expression(statement.value, function, state, context, depth),
                    )
                )
                self._assign(statement.target, value, state)
            elif isinstance(statement, ast.Expr):
                self._expression(statement.value, function, state, context, depth)
            elif isinstance(statement, ast.Return):
                returned.value = self._expression(statement.value, function, state, context, depth)
                return
            elif isinstance(statement, ast.If):
                left, right = dict(state), dict(state)
                self._block(statement.body, function, left, context, depth, returned)
                self._block(statement.orelse, function, right, context, depth, returned)
                state.update(left)
                state.update(right)
            elif isinstance(statement, ast.Try | ast.TryStar):
                self._block(statement.body, function, state, context, depth, returned)
                for handler in statement.handlers:
                    self._block(handler.body, function, dict(state), context, depth, returned)
                self._block(statement.orelse, function, state, context, depth, returned)
                self._block(statement.finalbody, function, state, context, depth, returned)
            elif isinstance(statement, ast.With | ast.AsyncWith):
                self._block(statement.body, function, state, context, depth, returned)
            elif isinstance(statement, ast.For | ast.AsyncFor | ast.While):
                self._block(statement.body, function, state, context, depth, returned)
                self._block(statement.orelse, function, state, context, depth, returned)

    def _function(
        self,
        function: PythonFunction,
        incoming: Mapping[str, _Taint],
        context: tuple[str, ...],
        depth: int,
    ) -> _Taint | None:
        if depth > self.limits.max_call_depth:
            self.index.coverage.add(coverage_limit("call-depth", function.function_id))
            return None
        signature = tuple(parameter in incoming for parameter in function.parameters)
        key = (function.function_id, signature)
        if key in self.active:
            self.index.coverage.add(coverage_limit("recursion", function.function_id))
            return None
        if self.contexts >= self.limits.max_contexts:
            self.index.coverage.add(coverage_limit("context-limit", self.contexts))
            return None
        self.contexts += 1
        self.active.add(key)
        try:
            state = dict(incoming)
            if function.entrypoint:
                self._entrypoint_sources(function, state, context)
            returned = _ReturnState()
            self._block(function.node.body, function, state, context, depth, returned)
            return returned.value
        finally:
            self.active.remove(key)

    def _entrypoint_sources(
        self, function: PythonFunction, state: dict[str, _Taint], context: tuple[str, ...]
    ) -> None:
        location = source_span(function.module.path, function.node)
        for parameter in function.parameters:
            if parameter in {"self", "cls"} or parameter in state:
                continue
            source_id = stable_id("source-param", function.function_id, parameter)
            self.index.nodes.setdefault(
                source_id,
                CodeGraphNode(
                    node_id=source_id,
                    kind=GraphNodeKind.SOURCE,
                    name=f"entrypoint parameter {parameter}",
                    span=location,
                ),
            )
            state[parameter] = _Taint(
                (_TracePoint(source_id, PathStepRole.SOURCE, location, context),)
            )

    def run(self) -> None:
        for function in sorted(self.index.functions.values(), key=lambda item: item.function_id):
            if function.entrypoint:
                self._function(function, {}, (function.function_id,), 0)


def _build_paths(
    analyzer: _Analyzer,
    graph: CodeGraphArtifact,
    rule: CodeSecurityRuleSpec,
    revision: str,
) -> tuple[PathEvidence, ...]:
    sanitizer_contexts = tuple(
        sorted(
            selector.security_context
            for selector in analyzer.sanitizers
            if selector.security_context is not None
        )
    )
    return tuple(
        PathEvidence(
            schema_version="1.0.0",
            revision=revision,
            graph_digest=graph.digest(),
            rule_id=rule.rule_id,
            rule_version=rule.version,
            steps=tuple(
                PathEvidenceStep(
                    node_id=point.node_id,
                    role=point.role,
                    span=point.span,
                    call_context=point.context,
                )
                for point in candidate
            ),
            sanitizers_considered=sanitizer_contexts,
            coverage_limits=graph.coverage_limits,
        )
        for candidate in analyzer.candidates
    )


def analyze_python_repository(
    root: Path,
    *,
    revision: str,
    build_context_digest: str,
    framework_model_digest: str,
    rule: CodeSecurityRuleSpec,
    limits: PythonAnalysisLimits | None = None,
) -> PythonAnalysisResult:
    """Build a deterministic graph and find bounded Python source-to-sink paths."""
    if "python" not in rule.languages or rule.analysis_kind is not RuleAnalysisKind.GRAPH_FLOW:
        raise ValueError("Python analysis requires a graph_flow rule that names python")
    selected_limits = limits or PythonAnalysisLimits()
    base = root.resolve(strict=True)
    if not base.is_dir():
        raise ValueError("analysis root must be a directory")
    index = build_python_graph_index(base, selected_limits)
    analyzer = _Analyzer(index, rule, selected_limits)
    analyzer.run()
    for candidate in analyzer.candidates:
        for left, right in zip(candidate, candidate[1:], strict=False):
            add_edge(index, GraphEdgeKind.FLOWS_TO, left.node_id, right.node_id)
    graph = CodeGraphArtifact(
        schema_version="1.0.0",
        revision=revision,
        build_context_digest=build_context_digest,
        framework_model_digest=framework_model_digest,
        frontend_versions={FRONTEND: VERSION},
        nodes=tuple(sorted(index.nodes.values(), key=lambda node: node.node_id)),
        edges=tuple(sorted(index.edges.values(), key=lambda edge: edge.edge_id)),
        coverage_limits=tuple(sorted(index.coverage)),
    )
    return PythonAnalysisResult(
        graph=graph,
        paths=_build_paths(analyzer, graph, rule, revision),
    )


__all__ = [
    "PythonAnalysisLimits",
    "PythonAnalysisResult",
    "analyze_python_repository",
]
