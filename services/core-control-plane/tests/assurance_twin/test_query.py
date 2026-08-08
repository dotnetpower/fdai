"""Text-to-query compiler + verifier contract (Wave A.3).

Every question either compiles to a well-typed, read-only
:class:`TypedQuery` and executes deterministically, or abstains -
never a mutation, never a guess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fdai.core.assurance_twin import (
    AbstainCode,
    AbstainResult,
    DeterministicPatternCompiler,
    InMemoryProjection,
    Predicate,
    PredicateOp,
    QueryKind,
    QueryVerificationError,
    QueryVerifier,
    TypedQuery,
    build_baseline_projection,
    execute_query,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.providers.projection import ResourceRef

REPO_ROOT = Path(__file__).resolve().parents[4]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


@pytest.fixture(scope="module")
def registry() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return load_resource_type_registry_from_mapping(raw)


@pytest.fixture()
def verifier(registry: ResourceTypeRegistry) -> QueryVerifier:
    return QueryVerifier(registry)


@pytest.fixture()
def compiler(registry: ResourceTypeRegistry) -> DeterministicPatternCompiler:
    return DeterministicPatternCompiler(registry)


def _ref(rtype: str, name: str) -> ResourceRef:
    return ResourceRef(resource_type=rtype, ref=name)


# ---------------------------------------------------------------------------
# Predicate / TypedQuery construction invariants.
# ---------------------------------------------------------------------------


class TestPredicateConstruction:
    def test_eq_requires_value(self) -> None:
        with pytest.raises(ValueError, match="requires a value"):
            Predicate(field="x", op=PredicateOp.EQ)

    def test_exists_forbids_value(self) -> None:
        with pytest.raises(ValueError, match="MUST NOT carry a value"):
            Predicate(field="x", op=PredicateOp.EXISTS, value=True)

    def test_missing_forbids_value(self) -> None:
        with pytest.raises(ValueError, match="MUST NOT carry a value"):
            Predicate(field="x", op=PredicateOp.MISSING, value=False)

    def test_in_requires_list_or_tuple(self) -> None:
        with pytest.raises(ValueError, match="list/tuple"):
            Predicate(field="x", op=PredicateOp.IN, value="not-a-list")

    def test_field_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            Predicate(field="", op=PredicateOp.EXISTS)

    def test_predicates_are_frozen(self) -> None:
        p = Predicate(field="x", op=PredicateOp.EXISTS)
        with pytest.raises((AttributeError, TypeError)):
            p.field = "y"  # type: ignore[misc]

    def test_typed_query_projection_must_be_non_empty_when_set(self) -> None:
        with pytest.raises(ValueError, match="None or a non-empty"):
            TypedQuery(resource_type="object-storage", predicates=(), projection=())

    def test_typed_query_projection_entries_must_be_strings(self) -> None:
        with pytest.raises(ValueError, match="non-empty strings"):
            TypedQuery(
                resource_type="object-storage",
                predicates=(),
                projection=("",),
            )

    def test_typed_query_requires_resource_type(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            TypedQuery(resource_type="", predicates=())


# ---------------------------------------------------------------------------
# Verifier fail-closed matrix.
# ---------------------------------------------------------------------------


class TestQueryVerifier:
    def test_accepts_shipped_resource_type(self, verifier: QueryVerifier) -> None:
        query = TypedQuery(resource_type="object-storage", predicates=())
        assert verifier.verify(query) is query

    def test_rejects_unknown_resource_type(self, verifier: QueryVerifier) -> None:
        query = TypedQuery(resource_type="not-a-known-type", predicates=())
        with pytest.raises(QueryVerificationError) as exc_info:
            verifier.verify(query)
        assert exc_info.value.kind == "unknown_resource_type"
        assert exc_info.value.field == "resource_type"

    def test_rejects_count_with_projection(self, verifier: QueryVerifier) -> None:
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(),
            kind=QueryKind.COUNT,
            projection=("id",),
        )
        with pytest.raises(QueryVerificationError) as exc_info:
            verifier.verify(query)
        assert exc_info.value.kind == "invalid_projection"

    def test_known_resource_types_is_read_only(self, verifier: QueryVerifier) -> None:
        assert isinstance(verifier.known_resource_types, frozenset)
        assert "object-storage" in verifier.known_resource_types

    def test_verification_error_is_a_value_error(self, verifier: QueryVerifier) -> None:
        query = TypedQuery(resource_type="does-not-exist", predicates=())
        with pytest.raises(ValueError):
            verifier.verify(query)


# ---------------------------------------------------------------------------
# Deterministic pattern compiler grammar.
# ---------------------------------------------------------------------------


class TestDeterministicPatternCompiler:
    def test_empty_input_abstains(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("   ")
        assert isinstance(result, AbstainResult)
        assert result.code is AbstainCode.EMPTY_INPUT

    def test_unrecognised_intent_abstains(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("please fix everything now")
        assert isinstance(result, AbstainResult)
        assert result.code is AbstainCode.UNRECOGNIZED_INTENT

    def test_unknown_resource_type_abstains(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list all quantum-widgets")
        assert isinstance(result, AbstainResult)
        assert result.code is AbstainCode.UNKNOWN_RESOURCE_TYPE

    def test_list_produces_find_query(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list all object-storage")
        assert isinstance(result, TypedQuery)
        assert result.kind is QueryKind.FIND
        assert result.resource_type == "object-storage"
        assert result.predicates == ()

    def test_count_produces_count_query(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("count object-storage")
        assert isinstance(result, TypedQuery)
        assert result.kind is QueryKind.COUNT

    def test_how_many_produces_count(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("how many object-storage exist")
        assert isinstance(result, TypedQuery)
        assert result.kind is QueryKind.COUNT

    def test_spaced_surface_form_matches(self, compiler: DeterministicPatternCompiler) -> None:
        # "object storage" should resolve to canonical "object-storage".
        result = compiler.compile("list object storage")
        assert isinstance(result, TypedQuery)
        assert result.resource_type == "object-storage"

    def test_without_maps_to_missing_predicate(
        self, compiler: DeterministicPatternCompiler
    ) -> None:
        result = compiler.compile("list object-storage without private_endpoint")
        assert isinstance(result, TypedQuery)
        assert result.predicates == (Predicate(field="private_endpoint", op=PredicateOp.MISSING),)

    def test_missing_marker_maps_to_missing_predicate(
        self, compiler: DeterministicPatternCompiler
    ) -> None:
        result = compiler.compile("list object-storage missing encryption")
        assert isinstance(result, TypedQuery)
        assert result.predicates == (Predicate(field="encryption", op=PredicateOp.MISSING),)

    def test_with_maps_to_exists_predicate(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list object-storage with encryption")
        assert isinstance(result, TypedQuery)
        assert result.predicates == (Predicate(field="encryption", op=PredicateOp.EXISTS),)

    def test_where_is_maps_to_eq_predicate(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list object-storage where public_access is true")
        assert isinstance(result, TypedQuery)
        assert result.predicates == (
            Predicate(field="public_access", op=PredicateOp.EQ, value=True),
        )

    def test_where_is_numeric_value(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list object-storage where retention is 7")
        assert isinstance(result, TypedQuery)
        assert result.predicates == (Predicate(field="retention", op=PredicateOp.EQ, value=7),)

    def test_where_is_string_value_unquoted(self, compiler: DeterministicPatternCompiler) -> None:
        result = compiler.compile("list object-storage where sku is premium")
        assert isinstance(result, TypedQuery)
        assert result.predicates[0].value == "premium"


# ---------------------------------------------------------------------------
# Compiler output ALWAYS clears the verifier (or is an AbstainResult).
# ---------------------------------------------------------------------------


class TestCompilerRespectsVerifier:
    @pytest.mark.parametrize(
        "nl_text",
        [
            "list object-storage",
            "count kubernetes-cluster",
            "list network.vnet without private_endpoint",
            "how many compute.vm",
            "list compute.vm where sku is standard",
        ],
    )
    def test_shipped_grammar_verifies(
        self,
        compiler: DeterministicPatternCompiler,
        verifier: QueryVerifier,
        nl_text: str,
    ) -> None:
        compiled = compiler.compile(nl_text)
        assert isinstance(compiled, TypedQuery)
        # MUST NOT raise.
        verifier.verify(compiled)

    def test_compiler_never_produces_mutation_op(
        self, compiler: DeterministicPatternCompiler
    ) -> None:
        # Even "delete/update/create" phrasing must abstain because
        # the compiler grammar cannot represent a mutation op.
        for text in ("delete all object-storage", "update object-storage"):
            result = compiler.compile(text)
            assert isinstance(result, AbstainResult), text


# ---------------------------------------------------------------------------
# execute_query() against InMemoryProjection.
# ---------------------------------------------------------------------------


def _build_projection() -> InMemoryProjection:
    baseline: list[tuple[ResourceRef, dict[str, Any]]] = [
        (_ref("object-storage", "a"), {"public_access": True, "sku": "standard"}),
        (_ref("object-storage", "b"), {"public_access": False, "sku": "premium"}),
        (_ref("object-storage", "c"), {"sku": "standard"}),  # missing public_access
        (_ref("compute.vm", "vm1"), {"sku": "standard"}),
    ]
    return build_baseline_projection(baseline)


class TestExecuteQuery:
    def test_find_returns_matching_rows_sorted(self) -> None:
        projection = _build_projection()
        query = TypedQuery(resource_type="object-storage", predicates=())
        result = execute_query(query, projection)
        assert result.count == 3
        assert [row.ref.ref for row in result.rows] == ["a", "b", "c"]

    def test_count_strips_rows(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(),
            kind=QueryKind.COUNT,
        )
        result = execute_query(query, projection)
        assert result.count == 3
        assert result.rows == ()

    def test_eq_predicate_filters(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(Predicate(field="public_access", op=PredicateOp.EQ, value=True),),
        )
        result = execute_query(query, projection)
        assert [row.ref.ref for row in result.rows] == ["a"]

    def test_ne_predicate_filters(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(Predicate(field="sku", op=PredicateOp.NE, value="standard"),),
        )
        result = execute_query(query, projection)
        assert [row.ref.ref for row in result.rows] == ["b"]

    def test_missing_predicate_matches_absent_field(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(Predicate(field="public_access", op=PredicateOp.MISSING),),
        )
        result = execute_query(query, projection)
        assert [row.ref.ref for row in result.rows] == ["c"]

    def test_exists_predicate(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(Predicate(field="public_access", op=PredicateOp.EXISTS),),
        )
        result = execute_query(query, projection)
        assert sorted(row.ref.ref for row in result.rows) == ["a", "b"]

    def test_in_predicate(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(
                Predicate(
                    field="sku",
                    op=PredicateOp.IN,
                    value=("premium", "ultra"),
                ),
            ),
        )
        result = execute_query(query, projection)
        assert [row.ref.ref for row in result.rows] == ["b"]

    def test_projection_returns_only_requested_fields(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(),
            projection=("sku",),
        )
        result = execute_query(query, projection)
        assert result.rows[0].properties == {"sku": "standard"}

    def test_ignores_other_resource_types(self) -> None:
        projection = _build_projection()
        query = TypedQuery(resource_type="compute.vm", predicates=())
        result = execute_query(query, projection)
        assert [row.ref.ref for row in result.rows] == ["vm1"]

    def test_empty_result_is_empty(self) -> None:
        projection = _build_projection()
        query = TypedQuery(
            resource_type="object-storage",
            predicates=(Predicate(field="sku", op=PredicateOp.EQ, value="nonexistent"),),
        )
        result = execute_query(query, projection)
        assert result.is_empty is True
        assert result.count == 0

    def test_deterministic_ordering_between_runs(self) -> None:
        projection = _build_projection()
        query = TypedQuery(resource_type="object-storage", predicates=())
        first = execute_query(query, projection)
        second = execute_query(query, projection)
        assert [r.ref for r in first.rows] == [r.ref for r in second.rows]

    def test_explicit_resources_iterable(self) -> None:
        # Real projections stream from Inventory - the caller passes
        # the materialised (ref, properties) view; the projection
        # argument is still required for Protocol compliance.
        projection = _build_projection()
        materialised: list[tuple[ResourceRef, dict[str, Any]]] = [
            (_ref("object-storage", "x"), {"public_access": True}),
        ]
        query = TypedQuery(resource_type="object-storage", predicates=())
        result = execute_query(query, projection, resources=materialised)
        assert [row.ref.ref for row in result.rows] == ["x"]

    def test_non_in_memory_projection_requires_resources(self) -> None:
        # A fake projection that satisfies the Protocol but is not
        # InMemoryProjection MUST get 'resources' provided explicitly.
        class _FakeProjection:
            def apply_diff(self, diff: Any) -> _FakeProjection:  # noqa: D401
                return self

            def evaluate(self, rules: Any) -> tuple[Any, ...]:  # noqa: D401
                return ()

        query = TypedQuery(resource_type="object-storage", predicates=())
        with pytest.raises(TypeError, match="explicit 'resources'"):
            execute_query(query, _FakeProjection(), resources=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# End-to-end: compile -> verify -> execute stays read-only.
# ---------------------------------------------------------------------------


def test_full_pipeline_grounds_a_question(
    compiler: DeterministicPatternCompiler,
    verifier: QueryVerifier,
) -> None:
    projection = _build_projection()
    compiled = compiler.compile("list object-storage without public_access")
    assert isinstance(compiled, TypedQuery)
    verified = verifier.verify(compiled)
    result = execute_query(verified, projection)
    assert [row.ref.ref for row in result.rows] == ["c"]


def test_pipeline_abstain_never_touches_projection(
    compiler: DeterministicPatternCompiler,
) -> None:
    projection = _build_projection()
    compiled = compiler.compile("please summarise everything")
    assert isinstance(compiled, AbstainResult)
    # The projection is untouched (still the original references).
    assert set(projection.resources) == {
        _ref("object-storage", "a"),
        _ref("object-storage", "b"),
        _ref("object-storage", "c"),
        _ref("compute.vm", "vm1"),
    }
