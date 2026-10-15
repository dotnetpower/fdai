"""Bounded tree-sitter Java interprocedural taint analysis for code security."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_java
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tree_sitter import Language, Node, Parser

from fdai.core.security.code_findings.analysis_contracts import (
    AnalysisProvenance,
    CodeGraphArtifact,
    CodeGraphEdge,
    CodeGraphNode,
    CodeSecurityRuleSpec,
    EvidenceConfidence,
    GraphEdgeKind,
    GraphNodeKind,
    PathEvidence,
    PathStepRole,
    RuleSelector,
    SourceSpan,
)
from fdai.core.security.code_findings.analysis_graph_flow import materialize_graph_paths

FRONTEND = "fdai.java.tree-sitter"
VERSION = "1.1.0"
COMPILER_FRONTEND = "javac"
_LANGUAGE = Language(tree_sitter_java.language())


@dataclass(frozen=True, slots=True)
class JavaAnalysisLimits:
    max_files: int = 2_000
    max_file_bytes: int = 2_000_000
    max_nodes: int = 100_000
    max_contexts: int = 10_000
    max_call_depth: int = 16
    max_paths: int = 1_000


@dataclass(frozen=True, slots=True)
class JavaCompilerConfig:
    java: Path
    helper: Path
    timeout_seconds: int = 60
    max_output_bytes: int = 5_000_000


class _CompilerFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=1_024)
    line: int = Field(ge=0, le=10_000_000)
    name: str | None = Field(default=None, max_length=256)
    text: str | None = Field(default=None, max_length=1_024)
    symbol: str = Field(max_length=1_024)
    type: str = Field(max_length=2_048)


class _CompilerDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str
    compiler_version: str = Field(min_length=1, max_length=64)
    methods: tuple[_CompilerFact, ...] = Field(max_length=100_000)
    calls: tuple[_CompilerFact, ...] = Field(max_length=200_000)
    error_count: int = Field(ge=0, le=1_000_000)


@dataclass(frozen=True, slots=True)
class _CompilerFacts:
    version: str
    methods: dict[tuple[str, int, str], str]
    calls: dict[tuple[str, int, str], str]
    error_count: int


@dataclass(frozen=True, slots=True)
class JavaAnalysisResult:
    graph: CodeGraphArtifact
    paths: tuple[PathEvidence, ...]


@dataclass(frozen=True, slots=True)
class _Method:
    path: str
    name: str
    node: Node
    parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Point:
    node_id: str
    role: PathStepRole
    span: SourceSpan
    context: tuple[str, ...]


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _field(node: Node, name: str) -> Node | None:
    return node.child_by_field_name(name)


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8") if node is not None and node.text is not None else ""


def _stable_id(*parts: object) -> str:
    value = "\0".join(str(part) for part in parts).encode()
    return f"java:{hashlib.sha256(value).hexdigest()[:24]}"


def _span(path: str, node: Node) -> SourceSpan:
    return SourceSpan(
        path=path,
        start_line=node.start_point.row + 1,
        start_column=node.start_point.column + 1,
        end_line=node.end_point.row + 1,
        end_column=max(node.end_point.column + 1, 1),
    )


def _read_source(root: Path, path: Path, limit: int) -> bytes:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.is_symlink():
        raise ValueError("Java source escapes the analysis root")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("Java source is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Java source exceeds the file byte limit")
        return content
    finally:
        os.close(descriptor)


class _Analyzer:
    def __init__(
        self,
        root: Path,
        revision: str,
        build_context_digest: str,
        framework_model_digest: str,
        rule: CodeSecurityRuleSpec,
        limits: JavaAnalysisLimits,
        compiler: _CompilerFacts | None,
    ) -> None:
        self.root = root
        self.revision = revision
        self.build_context_digest = build_context_digest
        self.framework_model_digest = framework_model_digest
        self.rule = rule
        self.limits = limits
        self.compiler = compiler
        self.nodes: dict[str, CodeGraphNode] = {}
        self.edges: dict[str, CodeGraphEdge] = {}
        self.methods: dict[str, list[_Method]] = {}
        self.coverage: set[str] = set()
        if compiler is not None and compiler.error_count:
            self.coverage.add(f"java.compiler-attribution-errors:{compiler.error_count}")
        self.paths: list[tuple[_Point, ...]] = []
        self.active: set[tuple[str, tuple[bool, ...]]] = set()
        self.contexts = 0
        self.provenance = AnalysisProvenance(
            frontend=FRONTEND,
            frontend_version=VERSION,
            model_version=VERSION,
            confidence=EvidenceConfidence.EXACT,
        )

    def _add_node(self, node: CodeGraphNode) -> None:
        if len(self.nodes) >= self.limits.max_nodes:
            self.coverage.add("java-graph-node-limit")
            return
        self.nodes.setdefault(node.node_id, node)

    def _add_edge(self, kind: GraphEdgeKind, source: str, target: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        edge_id = _stable_id("edge", kind, source, target)
        self.edges.setdefault(
            edge_id,
            CodeGraphEdge(
                edge_id=edge_id,
                kind=kind,
                source_id=source,
                target_id=target,
                provenance=self.provenance,
            ),
        )

    def _add_flow_edge(self, source: _Point, target: _Point) -> None:
        if source.node_id not in self.nodes or target.node_id not in self.nodes:
            return
        edge_id = _stable_id(
            "edge",
            GraphEdgeKind.FLOWS_TO,
            source.node_id,
            target.node_id,
            source.role,
            target.role,
            source.context,
            target.context,
        )
        self.edges.setdefault(
            edge_id,
            CodeGraphEdge(
                edge_id=edge_id,
                kind=GraphEdgeKind.FLOWS_TO,
                source_id=source.node_id,
                target_id=target.node_id,
                provenance=self.provenance,
                source_role=source.role,
                target_role=target.role,
                source_context=source.context,
                target_context=target.context,
            ),
        )

    @staticmethod
    def _matches(name: str, selector: RuleSelector) -> bool:
        return (
            name == selector.symbol
            or name.endswith(f".{selector.symbol}")
            or ("." not in selector.symbol and name.rsplit(".", 1)[-1] == selector.symbol)
        )

    def index(self) -> None:
        files: list[Path] = []
        for directory, directories, names in os.walk(self.root, followlinks=False):
            directories[:] = sorted(
                name for name in directories if not (Path(directory) / name).is_symlink()
            )
            for name in sorted(names):
                if name.endswith(".java"):
                    files.append(Path(directory) / name)
                    if len(files) > self.limits.max_files:
                        files.pop()
                        self.coverage.add("java-file-limit")
                        break
            if "java-file-limit" in self.coverage:
                break
        for path in files:
            relative = path.relative_to(self.root).as_posix()
            file_id = _stable_id("file", relative)
            self._add_node(CodeGraphNode(node_id=file_id, kind=GraphNodeKind.FILE, name=relative))
            try:
                source = _read_source(self.root, path, self.limits.max_file_bytes)
            except (OSError, ValueError):
                self.coverage.add(f"java-unreadable:{_stable_id(relative)}")
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                parser = Parser(_LANGUAGE, timeout_micros=100_000)
            tree = parser.parse(source)
            if tree.root_node.has_error:
                self.coverage.add(f"java-parse-error:{_stable_id(relative)}")
                continue
            for node in _walk(tree.root_node):
                if node.type not in {"method_declaration", "constructor_declaration"}:
                    continue
                name = _text(_field(node, "name"))
                if self.compiler is not None:
                    name = self.compiler.methods.get(
                        (relative, node.start_point.row + 1, name), name
                    )
                parameters_node = _field(node, "parameters")
                parameters = tuple(
                    _text(_field(item, "name"))
                    for item in (parameters_node.named_children if parameters_node else ())
                    if item.type in {"formal_parameter", "spread_parameter"}
                )
                method = _Method(relative, name, node, parameters)
                self.methods.setdefault(name.rsplit(".", 1)[-1], []).append(method)
                method_id = _stable_id("method", relative, name, node.start_byte)
                self._add_node(
                    CodeGraphNode(
                        node_id=method_id,
                        kind=GraphNodeKind.FUNCTION,
                        name=name,
                        span=_span(relative, node),
                    )
                )
                self._add_edge(GraphEdgeKind.DECLARES, file_id, method_id)

    def analyze(self) -> JavaAnalysisResult:
        self.index()
        for methods in self.methods.values():
            for method in methods:
                self._method(method, {}, ())
        for candidate in self.paths:
            for source, target in zip(candidate, candidate[1:], strict=False):
                self._add_flow_edge(source, target)
        if len(self.paths) > self.limits.max_paths:
            self.coverage.add("java-path-limit")
        graph = CodeGraphArtifact(
            schema_version="1.1.0",
            revision=self.revision,
            build_context_digest=self.build_context_digest,
            framework_model_digest=self.framework_model_digest,
            frontend_versions={
                FRONTEND: VERSION,
                **({COMPILER_FRONTEND: self.compiler.version} if self.compiler is not None else {}),
            },
            nodes=tuple(sorted(self.nodes.values(), key=lambda item: item.node_id)),
            edges=tuple(sorted(self.edges.values(), key=lambda item: item.edge_id)),
            coverage_limits=tuple(sorted(self.coverage)),
        )
        flow = materialize_graph_paths(graph, self.rule)
        return JavaAnalysisResult(graph=flow.graph, paths=flow.paths)

    def _method(
        self, method: _Method, arguments: dict[str, tuple[_Point, ...]], context: tuple[str, ...]
    ) -> tuple[_Point, ...] | None:
        key = (
            f"{method.path}:{method.node.start_byte}",
            tuple(bool(arguments.get(parameter)) for parameter in method.parameters),
        )
        if key in self.active or len(context) >= self.limits.max_call_depth:
            self.coverage.add("java-recursion-or-depth-limit")
            return None
        if self.contexts >= self.limits.max_contexts:
            self.coverage.add("java-context-limit")
            return None
        self.contexts += 1
        self.active.add(key)
        try:
            environment = dict(arguments)
            body = _field(method.node, "body")
            returned: tuple[_Point, ...] | None = None
            for node in _walk(body) if body is not None else ():
                if node.type == "variable_declarator":
                    name = _text(_field(node, "name"))
                    environment[name] = (
                        self._expression(_field(node, "value"), method, environment, context) or ()
                    )
                elif node.type == "assignment_expression":
                    left = _field(node, "left")
                    if left is not None and left.type == "identifier":
                        environment[_text(left)] = (
                            self._expression(_field(node, "right"), method, environment, context)
                            or ()
                        )
                elif node.type == "return_statement" and node.named_children:
                    returned = self._expression(
                        node.named_children[0], method, environment, context
                    )
                elif node.type == "expression_statement" and node.named_children:
                    self._expression(node.named_children[0], method, environment, context)
            return returned
        finally:
            self.active.remove(key)

    def _expression(
        self,
        node: Node | None,
        method: _Method,
        environment: dict[str, tuple[_Point, ...]],
        context: tuple[str, ...],
    ) -> tuple[_Point, ...] | None:
        if node is None:
            return None
        if node.type == "identifier":
            return environment.get(_text(node)) or None
        if node.type == "method_invocation":
            return self._call(node, method, environment, context)
        for child in node.named_children:
            if value := self._expression(child, method, environment, context):
                return value
        return None

    def _call(
        self,
        node: Node,
        method: _Method,
        environment: dict[str, tuple[_Point, ...]],
        context: tuple[str, ...],
    ) -> tuple[_Point, ...] | None:
        name_node = _field(node, "name")
        object_node = _field(node, "object")
        short_name = _text(name_node)
        name = ".".join(part for part in (_text(object_node), short_name) if part)
        if self.compiler is not None:
            name = self.compiler.calls.get((method.path, node.start_point.row + 1, name), name)
        location = _span(method.path, node)
        call_id = _stable_id("call", method.path, node.start_byte, name)
        self._add_node(
            CodeGraphNode(node_id=call_id, kind=GraphNodeKind.CALL_SITE, name=name, span=location)
        )
        source_selectors = [item for item in self.rule.selectors if item.role == "source"]
        if any(self._matches(name, item) for item in source_selectors):
            source_id = _stable_id("source", method.path, node.start_byte, name)
            self._add_node(
                CodeGraphNode(
                    node_id=source_id, kind=GraphNodeKind.SOURCE, name=name, span=location
                )
            )
            return (_Point(source_id, PathStepRole.SOURCE, location, context),)
        arguments_node = _field(node, "arguments")
        arguments = tuple(arguments_node.named_children) if arguments_node is not None else ()
        values = tuple(
            self._expression(argument, method, environment, context) for argument in arguments
        )
        sink_selectors = [item for item in self.rule.selectors if item.role == "sink"]
        for selector in sink_selectors:
            if not self._matches(name, selector):
                continue
            index = selector.argument_index or 0
            value = values[index] if index < len(values) else None
            if value:
                sink_id = _stable_id("sink", method.path, node.start_byte, name)
                self._add_node(
                    CodeGraphNode(
                        node_id=sink_id, kind=GraphNodeKind.SINK, name=name, span=location
                    )
                )
                if len(self.paths) < self.limits.max_paths:
                    self.paths.append(
                        value + (_Point(sink_id, PathStepRole.SINK, location, context),)
                    )
                else:
                    self.coverage.add("java-path-limit")
        targets = self.methods.get(short_name, [])
        if len(targets) == 1:
            target = targets[0]
            call_context = context + (call_id,)
            bindings = {
                parameter: value
                for parameter, value in zip(target.parameters, values, strict=False)
                if value
            }
            returned = self._method(target, bindings, call_context)
            if returned:
                point = _Point(call_id, PathStepRole.RETURN, location, context)
                self._add_edge(GraphEdgeKind.RETURNS_TO, returned[-1].node_id, call_id)
                return returned + (point,)
        elif len(targets) > 1 and any(values):
            self.coverage.add(f"java-ambiguous-call:{_stable_id(short_name)}")
        propagators = [item for item in self.rule.selectors if item.role == "propagator"]
        if any(self._matches(name, item) for item in propagators):
            receiver = self._expression(object_node, method, environment, context)
            return receiver or next((value for value in values if value), None)
        return next((value for value in values if value), None)


def analyze_java_repository(
    root: Path,
    *,
    revision: str,
    build_context_digest: str,
    framework_model_digest: str,
    rule: CodeSecurityRuleSpec,
    limits: JavaAnalysisLimits | None = None,
    compiler: JavaCompilerConfig | None = None,
) -> JavaAnalysisResult | None:
    """Analyze Java source under ``root`` without compiling or executing repository code."""
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Java analysis root must be a non-symlink directory")
    if not any(name.endswith(".java") for _, _, names in os.walk(resolved) for name in names):
        return None
    selected_limits = limits or JavaAnalysisLimits()
    compiler_facts = _compiler_facts(resolved, selected_limits, compiler) if compiler else None
    return _Analyzer(
        resolved,
        revision,
        build_context_digest,
        framework_model_digest,
        rule,
        selected_limits,
        compiler_facts,
    ).analyze()


def _compiler_facts(
    root: Path, limits: JavaAnalysisLimits, config: JavaCompilerConfig
) -> _CompilerFacts:
    java = config.java.resolve(strict=True)
    helper = config.helper.resolve(strict=True)
    if not java.is_file() or not helper.is_file() or helper.is_relative_to(root):
        raise ValueError("Java compiler bindings must be trusted files outside analyzed source")
    files = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.java")
        if path.is_file() and not path.is_symlink()
    )
    if not files or len(files) > limits.max_files:
        raise ValueError("Java compiler input exceeds the file limit")
    try:
        completed = subprocess.run(  # noqa: S603 - exact trusted executable and helper paths
            [str(java), "--add-modules", "jdk.compiler", str(helper), str(root), *files],
            capture_output=True,
            cwd=root,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            timeout=config.timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Java compiler frontend failed: {type(exc).__name__}") from exc
    if completed.returncode != 0 or len(completed.stdout) > config.max_output_bytes:
        raise ValueError("Java compiler frontend failed or exceeded its output limit")
    try:
        document = _CompilerDocument.model_validate_json(completed.stdout)
    except ValidationError as exc:
        raise ValueError("Java compiler frontend output violates its contract") from exc
    version_parts = document.compiler_version.split(".")
    if len(version_parts) < 3 or not all(part.isdigit() for part in version_parts[:3]):
        raise ValueError("Java compiler version is not numeric")
    version = ".".join(version_parts[:3])
    allowed = set(files)
    if any(item.path not in allowed for item in (*document.methods, *document.calls)):
        raise ValueError("Java compiler frontend returned a path outside the request")
    methods = {
        (item.path, item.line, item.name or ""): item.symbol
        for item in document.methods
        if item.name and item.symbol
    }
    calls = {
        (item.path, item.line, item.text or ""): item.symbol
        for item in document.calls
        if item.text and item.symbol
    }
    return _CompilerFacts(version, methods, calls, document.error_count)


__all__ = [
    "JavaAnalysisLimits",
    "JavaAnalysisResult",
    "JavaCompilerConfig",
    "analyze_java_repository",
]
