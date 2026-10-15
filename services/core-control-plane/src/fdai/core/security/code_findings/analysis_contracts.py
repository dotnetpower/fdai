"""Strict contracts for the owned code-security analysis engine.

These records are internal analysis artifacts. They are revision-bound, deterministic, and
separate from the operating ontology and authority-bearing control-plane contracts.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$"
_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_REVISION_PATTERN = r"^[a-f0-9]{40,64}$"
_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
_DOTTED_PATTERN = r"^[A-Za-z_$][A-Za-z0-9_$]*(\.[A-Za-z_$][A-Za-z0-9_$]*)*$"

GRAPH_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

Identifier = Annotated[str, Field(pattern=_ID_PATTERN)]
Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
Revision = Annotated[str, Field(pattern=_REVISION_PATTERN)]
Version = Annotated[str, Field(pattern=_VERSION_PATTERN)]
DottedName = Annotated[str, Field(pattern=_DOTTED_PATTERN)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    def canonical_bytes(self) -> bytes:
        """Return stable JSON bytes for replay, comparison, and content addressing."""
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


class GraphNodeKind(StrEnum):
    FILE = "file"
    FUNCTION = "function"
    SYMBOL = "symbol"
    CALL_SITE = "call_site"
    BASIC_BLOCK = "basic_block"
    DATA_FLOW = "data_flow"
    SOURCE = "source"
    SINK = "sink"
    SANITIZER = "sanitizer"


class GraphEdgeKind(StrEnum):
    DECLARES = "declares"
    CALLS = "calls"
    CONTROLS = "controls"
    DEFINES = "defines"
    USES = "uses"
    FLOWS_TO = "flows_to"
    ARGUMENT_TO = "argument_to"
    RETURNS_TO = "returns_to"
    ALIASES = "aliases"
    SANITIZES_FOR = "sanitizes_for"


class EvidenceConfidence(StrEnum):
    EXACT = "exact"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class SourceSpan(_StrictModel):
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    start_line: Annotated[int, Field(ge=1)]
    start_column: Annotated[int, Field(ge=1)] = 1
    end_line: Annotated[int, Field(ge=1)]
    end_column: Annotated[int, Field(ge=1)] = 1

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("source path must be normalized and repository-relative")
        return str(path)

    @model_validator(mode="after")
    def _ordered(self) -> SourceSpan:
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise ValueError("source span end must not precede its start")
        return self


class AnalysisProvenance(_StrictModel):
    frontend: Identifier
    frontend_version: Version
    model_version: Version
    confidence: EvidenceConfidence
    unresolved_alternatives: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _unresolved_is_explained(self) -> AnalysisProvenance:
        if self.confidence is EvidenceConfidence.UNRESOLVED and not self.unresolved_alternatives:
            raise ValueError("unresolved evidence requires at least one alternative")
        if self.confidence is not EvidenceConfidence.UNRESOLVED and self.unresolved_alternatives:
            raise ValueError("resolved evidence cannot carry unresolved alternatives")
        return self


class CodeGraphNode(_StrictModel):
    node_id: Identifier
    kind: GraphNodeKind
    name: Annotated[str, Field(min_length=1, max_length=512)]
    span: SourceSpan | None = None
    type_status: Literal["resolved", "partial", "unknown"] = "unknown"
    type_name: Annotated[str, Field(min_length=1, max_length=512)] | None = None

    @model_validator(mode="after")
    def _type_is_consistent(self) -> CodeGraphNode:
        if self.type_status == "resolved" and self.type_name is None:
            raise ValueError("resolved type status requires a type name")
        if self.type_status == "unknown" and self.type_name is not None:
            raise ValueError("unknown type status cannot carry a type name")
        return self


class CodeGraphEdge(_StrictModel):
    edge_id: Identifier
    kind: GraphEdgeKind
    source_id: Identifier
    target_id: Identifier
    provenance: AnalysisProvenance
    parameter_index: Annotated[int, Field(ge=0, le=1024)] | None = None
    security_context: Identifier | None = None

    @model_validator(mode="after")
    def _edge_fields_match_kind(self) -> CodeGraphEdge:
        if self.kind is GraphEdgeKind.ARGUMENT_TO and self.parameter_index is None:
            raise ValueError("argument_to edge requires parameter_index")
        if self.kind is not GraphEdgeKind.ARGUMENT_TO and self.parameter_index is not None:
            raise ValueError("parameter_index is valid only for argument_to edges")
        if self.kind is GraphEdgeKind.SANITIZES_FOR and self.security_context is None:
            raise ValueError("sanitizes_for edge requires security_context")
        if self.kind is not GraphEdgeKind.SANITIZES_FOR and self.security_context is not None:
            raise ValueError("security_context is valid only for sanitizes_for edges")
        return self


class CodeGraphArtifact(_StrictModel):
    schema_version: Literal["1.0.0"]
    revision: Revision
    build_context_digest: Digest
    framework_model_digest: Digest
    frontend_versions: dict[Identifier, Version]
    nodes: Annotated[tuple[CodeGraphNode, ...], Field(min_length=1)]
    edges: tuple[CodeGraphEdge, ...] = ()
    coverage_limits: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _closed_graph(self) -> CodeGraphArtifact:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("graph node ids must be unique")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("graph edge ids must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_id not in known or edge.target_id not in known:
                raise ValueError("graph edge references an unknown node")
        if not self.frontend_versions:
            raise ValueError("graph artifact requires at least one frontend version")
        return self


class RuleAnalysisKind(StrEnum):
    AST = "ast"
    TYPED = "typed"
    GRAPH_FLOW = "graph_flow"


class RuleSelector(_StrictModel):
    role: Literal["source", "sink", "propagator", "sanitizer"]
    symbol: DottedName
    argument_index: Annotated[int, Field(ge=0, le=1024)] | None = None
    security_context: Identifier | None = None

    @model_validator(mode="after")
    def _sanitizer_context(self) -> RuleSelector:
        if self.role == "sanitizer" and self.security_context is None:
            raise ValueError("sanitizer selector requires security_context")
        if self.role != "sanitizer" and self.security_context is not None:
            raise ValueError("security_context is valid only for sanitizer selectors")
        return self


class CodeSecurityRuleSpec(_StrictModel):
    schema_version: Literal["1.0.0"]
    rule_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]{2,127}$")]
    version: Version
    analysis_kind: RuleAnalysisKind
    languages: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    cwe_ids: Annotated[tuple[Annotated[int, Field(ge=1, le=9999)], ...], Field(min_length=1)]
    selectors: Annotated[tuple[RuleSelector, ...], Field(min_length=2)]
    vulnerable_cases: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    safe_cases: Annotated[tuple[Identifier, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _complete_flow_rule(self) -> CodeSecurityRuleSpec:
        roles = {selector.role for selector in self.selectors}
        if self.analysis_kind is RuleAnalysisKind.GRAPH_FLOW and not {"source", "sink"} <= roles:
            raise ValueError("graph_flow rule requires source and sink selectors")
        if len(self.languages) != len(set(self.languages)):
            raise ValueError("rule languages must be unique")
        if len(self.languages) != 1:
            raise ValueError("analysis rules must bind exactly one language frontend")
        if len(self.cwe_ids) != len(set(self.cwe_ids)):
            raise ValueError("rule CWE ids must be unique")
        return self


class PathStepRole(StrEnum):
    SOURCE = "source"
    FLOW = "flow"
    CALL = "call"
    RETURN = "return"
    SANITIZER = "sanitizer"
    SINK = "sink"


class PathEvidenceStep(_StrictModel):
    node_id: Identifier
    role: PathStepRole
    span: SourceSpan
    call_context: tuple[Identifier, ...] = ()


class PathEvidence(_StrictModel):
    schema_version: Literal["1.0.0"]
    revision: Revision
    graph_digest: Digest
    rule_id: Identifier
    rule_version: Version
    steps: Annotated[tuple[PathEvidenceStep, ...], Field(min_length=2, max_length=256)]
    sanitizers_considered: tuple[Identifier, ...] = ()
    coverage_limits: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _ordered_path(self) -> PathEvidence:
        if self.steps[0].role is not PathStepRole.SOURCE:
            raise ValueError("path evidence must start at a source")
        if self.steps[-1].role is not PathStepRole.SINK:
            raise ValueError("path evidence must end at a sink")
        if len({(step.node_id, step.role, step.call_context) for step in self.steps}) != len(
            self.steps
        ):
            raise ValueError("path evidence cannot repeat the same contextual step")
        return self


__all__ = [
    "AnalysisProvenance",
    "CodeGraphArtifact",
    "CodeGraphEdge",
    "CodeGraphNode",
    "CodeSecurityRuleSpec",
    "EvidenceConfidence",
    "GraphEdgeKind",
    "GraphNodeKind",
    "GRAPH_SCHEMA_VERSION",
    "PathEvidence",
    "PathEvidenceStep",
    "PathStepRole",
    "RuleAnalysisKind",
    "RuleSelector",
    "SourceSpan",
]
