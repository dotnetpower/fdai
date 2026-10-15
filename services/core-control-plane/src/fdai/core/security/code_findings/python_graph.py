"""Deterministic Python AST frontend for the owned code-security graph."""

from __future__ import annotations

import ast
import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fdai.core.security.code_findings.analysis_contracts import (
    AnalysisProvenance,
    CodeGraphEdge,
    CodeGraphNode,
    EvidenceConfidence,
    GraphEdgeKind,
    GraphNodeKind,
    SourceSpan,
)

FRONTEND = "python-ast"
VERSION = "1.0.0"
_ENTRYPOINT_DECORATORS = frozenset(
    {"route", "get", "post", "put", "patch", "delete", "api_route", "websocket"}
)


@dataclass(frozen=True, slots=True)
class PythonAnalysisLimits:
    max_files: int = 5000
    max_file_bytes: int = 1_000_000
    max_functions: int = 50_000
    max_call_depth: int = 12
    max_contexts: int = 100_000
    max_paths: int = 5000
    max_graph_nodes: int = 100_000


@dataclass(frozen=True, slots=True)
class PythonModule:
    path: str
    name: str
    tree: ast.Module
    imports: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PythonFunction:
    function_id: str
    module: PythonModule
    qualified_name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    parameters: tuple[str, ...]
    entrypoint: bool


@dataclass(slots=True)
class PythonGraphIndex:
    functions: dict[str, PythonFunction] = field(default_factory=dict)
    module_functions: dict[tuple[str, str], str] = field(default_factory=dict)
    nodes: dict[str, CodeGraphNode] = field(default_factory=dict)
    edges: dict[str, CodeGraphEdge] = field(default_factory=dict)
    coverage: set[str] = field(default_factory=set)


def stable_id(prefix: str, *parts: object) -> str:
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()[:24]}"


def coverage_limit(kind: str, *parts: object) -> str:
    return stable_id(f"python.{kind}", *parts)


def source_span(path: str, node: ast.AST) -> SourceSpan:
    start_line = getattr(node, "lineno", 1)
    start_column = getattr(node, "col_offset", 0) + 1
    return SourceSpan(
        path=path,
        start_line=start_line,
        start_column=start_column,
        end_line=getattr(node, "end_lineno", start_line),
        end_column=getattr(node, "end_col_offset", start_column - 1) + 1,
    )


def _module_name(path: str) -> str:
    parts = list(Path(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(tree: ast.Module, module_name: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    package = module_name.rpartition(".")[0]
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            base = node.module
            if node.level and package:
                parent = package.split(".")
                base = ".".join([*parent[: -node.level + 1 or None], node.module])
            for item in node.names:
                aliases[item.asname or item.name] = f"{base}.{item.name}"
    return aliases


def _raw_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _raw_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def resolved_name(node: ast.AST, module: PythonModule) -> str | None:
    raw = _raw_name(node)
    if raw is None:
        return None
    head, _, tail = raw.partition(".")
    base = module.imports.get(head, head)
    return f"{base}.{tail}" if tail else base


def _decorated_entrypoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = _raw_name(target)
        if name and name.rsplit(".", 1)[-1] in _ENTRYPOINT_DECORATORS:
            return True
    return False


def _provenance(confidence: EvidenceConfidence = EvidenceConfidence.EXACT) -> AnalysisProvenance:
    return AnalysisProvenance(
        frontend=FRONTEND,
        frontend_version=VERSION,
        model_version=VERSION,
        confidence=confidence,
    )


def add_edge(
    index: PythonGraphIndex,
    kind: GraphEdgeKind,
    source_id: str,
    target_id: str,
    *,
    parameter_index: int | None = None,
) -> None:
    edge_id = stable_id("edge", kind, source_id, target_id, parameter_index)
    confidence = (
        EvidenceConfidence.INFERRED if kind is GraphEdgeKind.CALLS else EvidenceConfidence.EXACT
    )
    index.edges.setdefault(
        edge_id,
        CodeGraphEdge(
            edge_id=edge_id,
            kind=kind,
            source_id=source_id,
            target_id=target_id,
            provenance=_provenance(confidence),
            parameter_index=parameter_index,
        ),
    )


def _iter_functions(
    module: PythonModule,
) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for node in module.tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield f"{node.name}.{member.name}", member


def _function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    arguments = node.args
    values = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    values.extend(item for item in (arguments.vararg, arguments.kwarg) if item is not None)
    return tuple(item.arg for item in values)


def _load_modules(
    root: Path, limits: PythonAnalysisLimits, index: PythonGraphIndex
) -> tuple[PythonModule, ...]:
    paths = sorted(path for path in root.rglob("*.py") if path.is_file())
    if len(paths) > limits.max_files:
        index.coverage.add(coverage_limit("file-limit", len(paths)))
        paths = paths[: limits.max_files]
    modules: list[PythonModule] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        file_id = stable_id("file", relative)
        if len(index.nodes) >= limits.max_graph_nodes:
            index.coverage.add(coverage_limit("graph-node-limit", len(index.nodes)))
            break
        if path.is_symlink():
            index.coverage.add(coverage_limit("symlink", relative))
            continue
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                index.coverage.add(coverage_limit("path-escape", relative))
                continue
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                source = handle.read(limits.max_file_bytes + 1)
        except OSError:
            index.coverage.add(coverage_limit("read", relative))
            continue
        end_line = max(1, source.count(b"\n") + 1)
        index.nodes[file_id] = CodeGraphNode(
            node_id=file_id,
            kind=GraphNodeKind.FILE,
            name=relative,
            span=SourceSpan(path=relative, start_line=1, end_line=end_line),
        )
        if size > limits.max_file_bytes or len(source) > limits.max_file_bytes:
            index.coverage.add(coverage_limit("file-size", relative))
            continue
        try:
            tree = ast.parse(source, filename=relative)
        except (SyntaxError, ValueError, UnicodeError):
            index.coverage.add(coverage_limit("parse", relative))
            continue
        name = _module_name(relative)
        modules.append(PythonModule(relative, name, tree, _imports(tree, name)))
    return tuple(modules)


def _index_functions(
    modules: Sequence[PythonModule], limits: PythonAnalysisLimits, index: PythonGraphIndex
) -> None:
    for module in modules:
        file_id = stable_id("file", module.path)
        for qualified_name, node in _iter_functions(module):
            if len(index.functions) >= limits.max_functions:
                index.coverage.add(coverage_limit("function-limit", len(index.functions)))
                return
            required_nodes = 2 + len(_function_parameters(node))
            if len(index.nodes) + required_nodes > limits.max_graph_nodes:
                index.coverage.add(coverage_limit("graph-node-limit", len(index.nodes)))
                return
            full_name = f"{module.name}.{qualified_name}" if module.name else qualified_name
            function_id = stable_id("function", module.path, qualified_name, node.lineno)
            function = PythonFunction(
                function_id,
                module,
                qualified_name,
                node,
                _function_parameters(node),
                _decorated_entrypoint(node),
            )
            index.functions[function_id] = function
            index.module_functions[(module.name, qualified_name)] = function_id
            index.nodes[function_id] = CodeGraphNode(
                node_id=function_id,
                kind=GraphNodeKind.FUNCTION,
                name=full_name,
                span=source_span(module.path, node),
            )
            add_edge(index, GraphEdgeKind.DECLARES, file_id, function_id)
            block_id = stable_id("block", function_id)
            index.nodes[block_id] = CodeGraphNode(
                node_id=block_id,
                kind=GraphNodeKind.BASIC_BLOCK,
                name=f"{full_name}:entry",
                span=source_span(module.path, node),
            )
            add_edge(index, GraphEdgeKind.CONTROLS, function_id, block_id)
            for parameter in function.parameters:
                symbol_id = stable_id("symbol", function_id, parameter)
                index.nodes[symbol_id] = CodeGraphNode(
                    node_id=symbol_id,
                    kind=GraphNodeKind.SYMBOL,
                    name=parameter,
                    span=source_span(module.path, node),
                )
                add_edge(index, GraphEdgeKind.DECLARES, function_id, symbol_id)


def resolve_call(
    call: ast.Call, function: PythonFunction, index: PythonGraphIndex
) -> PythonFunction | None:
    raw = _raw_name(call.func)
    if raw is None:
        return None
    if isinstance(call.func, ast.Name):
        imported = function.module.imports.get(raw)
        if imported:
            module_name, _, name = imported.rpartition(".")
            target = index.module_functions.get((module_name, name))
        else:
            target = index.module_functions.get((function.module.name, raw))
    elif raw.startswith("self.") and "." in function.qualified_name:
        owner = function.qualified_name.rpartition(".")[0]
        target = index.module_functions.get((function.module.name, f"{owner}.{raw[5:]}"))
    else:
        resolved = resolved_name(call.func, function.module) or raw
        module_name, _, name = resolved.rpartition(".")
        target = index.module_functions.get((module_name, name))
    return index.functions.get(target) if target else None


def _index_calls(index: PythonGraphIndex, limits: PythonAnalysisLimits) -> None:
    for function in index.functions.values():
        block_id = stable_id("block", function.function_id)
        for call in (node for node in ast.walk(function.node) if isinstance(node, ast.Call)):
            if len(index.nodes) >= limits.max_graph_nodes:
                index.coverage.add(coverage_limit("graph-node-limit", len(index.nodes)))
                return
            call_id = stable_id("call", function.module.path, call.lineno, call.col_offset)
            name = resolved_name(call.func, function.module) or "unresolved"
            index.nodes.setdefault(
                call_id,
                CodeGraphNode(
                    node_id=call_id,
                    kind=GraphNodeKind.CALL_SITE,
                    name=name,
                    span=source_span(function.module.path, call),
                ),
            )
            add_edge(index, GraphEdgeKind.CONTROLS, block_id, call_id)
            target = resolve_call(call, function, index)
            if target:
                add_edge(index, GraphEdgeKind.CALLS, call_id, target.function_id)


def build_python_graph_index(root: Path, limits: PythonAnalysisLimits) -> PythonGraphIndex:
    """Parse bounded Python inputs and index files, functions, symbols, and calls."""
    index = PythonGraphIndex()
    modules = _load_modules(root, limits, index)
    _index_functions(modules, limits, index)
    _index_calls(index, limits)
    return index


__all__ = [
    "FRONTEND",
    "VERSION",
    "PythonAnalysisLimits",
    "PythonFunction",
    "PythonGraphIndex",
    "add_edge",
    "build_python_graph_index",
    "coverage_limit",
    "resolve_call",
    "resolved_name",
    "source_span",
    "stable_id",
]
