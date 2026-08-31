"""Text-to-query compiler + verifier for the Assurance Twin (Wave A.3).

Implements the P2 twin query surface described in the Assurance Twin
doc's verifiable section (see ``docs/roadmap/operations/assurance-twin.md``, the
"Verifiable (text-to-query, not text-to-answer)" heading):
a natural-language question compiles into a **typed, read-only, well-typed**
:class:`TypedQuery` that runs deterministically against the twin
projection. The compiler MAY be an LLM in a fork; the verifier is the
authority. Anything a compiler cannot produce is an
:class:`AbstainResult`, never a mutation.

Two invariants that this module enforces regardless of the compiler:

1. **Read-only** - a :class:`TypedQuery` has no verbs that mutate. The
   :class:`QueryVerifier` rejects any query whose ``resource_type`` is
   not in the shipped vocabulary or whose predicate op is not in the
   read-only allow-list. There is no "update" op; there never will be.
2. **Well-typed** - the ``resource_type`` MUST exist in the
   :class:`ResourceTypeRegistry` and every predicate field MUST be a
   non-empty string. Nothing else is inferred; the twin never
   fabricates.

The shipped compiler explicitly abstains until a schema-validated semantic
model compiler is injected. Every proposed query still passes the verifier.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.shared.providers.projection import ResourceRef, ScratchProjection


class QueryKind(StrEnum):
    """What shape of result the query wants back.

    All kinds are read-only. There is deliberately no ``update`` or
    ``delete``; the compiler cannot even represent a mutation.
    """

    FIND = "find"
    COUNT = "count"


class PredicateOp(StrEnum):
    """Predicate operators the verifier accepts.

    Mutation-flavoured verbs (``set``, ``remove``, ``create``) are
    intentionally absent - see the read-only invariant above.
    """

    EQ = "eq"
    NE = "ne"
    EXISTS = "exists"
    MISSING = "missing"
    IN = "in"


_READ_ONLY_OPS: frozenset[str] = frozenset(op.value for op in PredicateOp)


class AbstainCode(StrEnum):
    """Why the compiler produced no query."""

    UNRECOGNIZED_INTENT = "unrecognized_intent"
    UNKNOWN_RESOURCE_TYPE = "unknown_resource_type"
    EMPTY_INPUT = "empty_input"
    AMBIGUOUS = "ambiguous"
    SEMANTIC_MODEL_UNAVAILABLE = "semantic_model_unavailable"


@dataclass(frozen=True, slots=True)
class Predicate:
    """One field / op / value tuple.

    ``value`` is only meaningful for :attr:`PredicateOp.EQ`,
    :attr:`PredicateOp.NE`, and :attr:`PredicateOp.IN`; the boolean
    ``EXISTS`` / ``MISSING`` ops MUST leave it as ``None``.
    """

    field: str
    op: PredicateOp
    value: Any = None

    def __post_init__(self) -> None:
        if not self.field or not isinstance(self.field, str):
            raise ValueError("Predicate.field MUST be a non-empty string")
        needs_value = self.op in (PredicateOp.EQ, PredicateOp.NE, PredicateOp.IN)
        if needs_value and self.value is None:
            raise ValueError(f"Predicate op {self.op.value!r} requires a value")
        if not needs_value and self.value is not None:
            raise ValueError(f"Predicate op {self.op.value!r} MUST NOT carry a value")
        if self.op is PredicateOp.IN and not isinstance(self.value, (list, tuple)):
            raise ValueError("Predicate op 'in' requires a list/tuple value")


@dataclass(frozen=True, slots=True)
class TypedQuery:
    """A verified, read-only ontology query.

    Instances are only constructed through
    :meth:`QueryVerifier.verify` or by callers that already hold a
    verified query. The dataclass is frozen so the query object is
    safe to cache and to pass across trust boundaries.
    """

    resource_type: str
    predicates: tuple[Predicate, ...]
    kind: QueryKind = QueryKind.FIND
    projection: tuple[str, ...] | None = None
    limit: int = 100
    evidence_refs: tuple[str, ...] = ()
    compiler_revision: str | None = None
    input_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_type:
            raise ValueError("TypedQuery.resource_type MUST be non-empty")
        if self.projection is not None:
            if not self.projection:
                raise ValueError("TypedQuery.projection MUST be None or a non-empty tuple")
            for field_name in self.projection:
                if not field_name or not isinstance(field_name, str):
                    raise ValueError("TypedQuery.projection entries MUST be non-empty strings")
        if not 1 <= self.limit <= 200:
            raise ValueError("TypedQuery.limit MUST be in [1, 200]")


@dataclass(frozen=True, slots=True)
class AbstainResult:
    """The compiler chose to answer "not known" instead of guessing."""

    code: AbstainCode
    reason: str
    hint: str | None = None


CompiledQuery = TypedQuery | AbstainResult


class QueryVerificationError(ValueError):
    """Raised by :meth:`QueryVerifier.verify` on a rejection.

    Mirrors the T2 quality-gate verifier posture: fail closed, cite the
    offending field, no partial acceptance. The ``kind`` attribute lets
    callers distinguish policy from schema failures without parsing the
    message string.
    """

    __slots__ = ("kind", "field")

    def __init__(
        self,
        *,
        kind: Literal[
            "unknown_resource_type",
            "unknown_op",
            "invalid_predicate",
            "invalid_projection",
        ],
        message: str,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.field = field


class QueryVerifier:
    """Validates a proposed :class:`TypedQuery` before execution.

    The verifier is the authority - a compiler may propose anything,
    but only queries that clear this check reach
    :func:`execute_query`. Mirrors the T2 quality-gate verifier
    posture: fail closed, cite the field, no partial acceptance.
    """

    def __init__(
        self,
        resource_types: ResourceTypeRegistry,
        *,
        require_compiler_evidence: bool = False,
    ) -> None:
        self._known_resource_types: frozenset[str] = frozenset(resource_types.ids())
        self._require_compiler_evidence = require_compiler_evidence

    @property
    def known_resource_types(self) -> frozenset[str]:
        return self._known_resource_types

    def verify(
        self,
        query: TypedQuery,
        *,
        expected_input_digest: str | None = None,
    ) -> TypedQuery:
        """Return ``query`` unchanged, or raise :class:`QueryVerificationError`."""
        if query.resource_type not in self._known_resource_types:
            raise QueryVerificationError(
                kind="unknown_resource_type",
                message=(f"resource_type {query.resource_type!r} is not in the shipped vocabulary"),
                field="resource_type",
            )
        for predicate in query.predicates:
            if predicate.op.value not in _READ_ONLY_OPS:
                raise QueryVerificationError(
                    kind="unknown_op",
                    message=f"predicate op {predicate.op.value!r} is not read-only",
                    field=f"predicate:{predicate.field}",
                )
        if query.projection is not None and query.kind is QueryKind.COUNT:
            raise QueryVerificationError(
                kind="invalid_projection",
                message="COUNT queries MUST NOT carry a field projection",
                field="projection",
            )
        if self._require_compiler_evidence:
            if not query.compiler_revision or not query.compiler_revision.strip():
                raise QueryVerificationError(
                    kind="invalid_projection",
                    message="compiler output MUST name its revision",
                    field="compiler_revision",
                )
            if not query.evidence_refs or any(
                not item.strip() or len(item) > 512 for item in query.evidence_refs
            ):
                raise QueryVerificationError(
                    kind="invalid_projection",
                    message="compiler output MUST cite bounded evidence refs",
                    field="evidence_refs",
                )
            if query.input_digest != expected_input_digest:
                raise QueryVerificationError(
                    kind="invalid_projection",
                    message="compiler output input digest does not match the question",
                    field="input_digest",
                )
        return query


@runtime_checkable
class NlQueryCompiler(Protocol):
    """Compile natural-language text into a :class:`CompiledQuery`.

    Implementations MUST be side-effect-free. The narrator LLM binding
    a fork installs implements this protocol; the deterministic
    baseline below is the default when no narrator is configured.
    """

    def compile(self, nl_text: str) -> CompiledQuery: ...


class DeterministicPatternCompiler:
    """Compatibility default that explicitly abstains without a semantic model."""

    def __init__(self, resource_types: ResourceTypeRegistry) -> None:
        self._known_resource_types = frozenset(resource_types.ids())

    def compile(self, nl_text: str) -> CompiledQuery:
        if not (nl_text or "").strip():
            return AbstainResult(code=AbstainCode.EMPTY_INPUT, reason="input text is empty")
        return AbstainResult(
            code=AbstainCode.SEMANTIC_MODEL_UNAVAILABLE,
            reason="semantic query compiler is unavailable",
        )


# ---------------------------------------------------------------------------
# Query execution over an in-memory / read-only projection.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QueryRow:
    """One projected resource returned by a FIND query.

    ``properties`` is the subset requested by ``TypedQuery.projection``
    or the full property mapping when no projection is set. It is a
    read-only mapping; callers MUST NOT mutate it.
    """

    ref: ResourceRef
    properties: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Return type of :func:`execute_query`.

    ``rows`` is populated for FIND queries; ``count`` is populated for
    COUNT queries; both are always set to keep the type
    unconditional.
    """

    query: TypedQuery
    rows: tuple[QueryRow, ...]
    count: int

    @property
    def is_empty(self) -> bool:
        return self.count == 0


def _predicate_matches(props: Mapping[str, Any], predicate: Predicate) -> bool:
    if predicate.op is PredicateOp.EXISTS:
        return predicate.field in props
    if predicate.op is PredicateOp.MISSING:
        return predicate.field not in props
    if predicate.field not in props:
        # Any value-carrying op on a missing field is a non-match; we
        # never raise from execute because the projection is authoritative.
        return False
    actual = props[predicate.field]
    if predicate.op is PredicateOp.EQ:
        return bool(actual == predicate.value)
    if predicate.op is PredicateOp.NE:
        return bool(actual != predicate.value)
    if predicate.op is PredicateOp.IN:
        # value is guaranteed to be list/tuple by Predicate.__post_init__.
        return bool(actual in predicate.value)
    # StrEnum guarantees exhaustiveness; keep the branch for mypy.
    return False  # pragma: no cover


def execute_query(
    query: TypedQuery,
    projection: ScratchProjection,
    *,
    resources: Sequence[tuple[ResourceRef, Mapping[str, Any]]] | None = None,
) -> QueryResult:
    """Run a verified :class:`TypedQuery` over ``projection``.

    ``resources`` is an optional pre-materialised iterable of
    ``(ref, properties)`` pairs. Callers that hold an
    :class:`~fdai.core.assurance_twin.InMemoryProjection` can
    pass ``None`` and the function reads its resources directly. Real
    projections that stream from Inventory MUST pass their materialised
    view.

    Rows are returned in lexicographic ``ref`` order so the output is
    deterministic and reproducible across calls (see the
    ontology-grounded section of ``docs/roadmap/operations/assurance-twin.md``).
    """

    if resources is None:
        # Local import; ``core.assurance_twin.projection`` already
        # imports from ``shared/providers/projection.py`` so this stays
        # inside the core-only-imports-from-shared boundary.
        from fdai.core.assurance_twin.projection import InMemoryProjection

        if not isinstance(projection, InMemoryProjection):
            raise TypeError(
                "execute_query requires an InMemoryProjection or an explicit "
                "'resources' argument for other projection backends"
            )
        materialised: list[tuple[ResourceRef, Mapping[str, Any]]] = [
            (proj.ref, projection.properties(proj.ref)) for proj in projection.resources.values()
        ]
    else:
        materialised = [(ref, dict(props)) for ref, props in resources]

    matches: list[QueryRow] = []
    for ref, props in materialised:
        if ref.resource_type != query.resource_type:
            continue
        if any(not _predicate_matches(props, p) for p in query.predicates):
            continue
        selected: Mapping[str, Any]
        if query.projection is None:
            selected = dict(props)
        else:
            selected = {k: props[k] for k in query.projection if k in props}
        matches.append(QueryRow(ref=ref, properties=selected))

    matches.sort(key=lambda row: (row.ref.resource_type, row.ref.ref))
    count = len(matches)
    rows = tuple(matches[: query.limit])
    if query.kind is QueryKind.COUNT:
        # COUNT strips the row payload to keep the result small; the
        # count is authoritative.
        rows = ()
    return QueryResult(query=query, rows=rows, count=count)


__all__ = [
    "AbstainCode",
    "AbstainResult",
    "CompiledQuery",
    "DeterministicPatternCompiler",
    "NlQueryCompiler",
    "Predicate",
    "PredicateOp",
    "QueryKind",
    "QueryResult",
    "QueryRow",
    "QueryVerificationError",
    "QueryVerifier",
    "TypedQuery",
    "execute_query",
]
