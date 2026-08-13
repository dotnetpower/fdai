"""Deterministic properties of graph-generation comparison."""

from __future__ import annotations

from itertools import permutations

from fdai.core.ontology_platform.direction_shadow import (
    ComparisonBounds,
    ComparisonDisposition,
    DirectionGraphGeneration,
    DirectionGraphLink,
    RebuildPointer,
    ReviewReason,
    compare_graph_generations,
    replay_matches,
)

PRIOR_RELEASE = "sha256:" + "c" * 64
ALIGNED_RELEASE = "sha256:" + "d" * 64
POINTER = RebuildPointer(
    authoritative_generation_ref="inventory-generation:property",
    rebuild_procedure_ref="runbook:ontology-current-state-rebuild:v1",
)


def _generation(
    reference: str,
    release: str | None,
    object_ids: tuple[str, ...],
    links: tuple[DirectionGraphLink, ...],
    *,
    complete: bool = True,
    truncated: bool = False,
) -> DirectionGraphGeneration:
    return DirectionGraphGeneration.create(
        generation_ref=reference,
        ontology_release_digest=release,
        object_ids=object_ids,
        links=links,
        complete=complete,
        truncated=truncated,
    )


def test_generation_and_receipt_identity_are_input_order_independent() -> None:
    objects = ("parent", "child", "dependent", "prerequisite")
    legacy_links = (
        DirectionGraphLink("contains", "child", "parent"),
        DirectionGraphLink("depends_on", "prerequisite", "dependent"),
    )
    aligned_links = (
        DirectionGraphLink("contains", "parent", "child"),
        DirectionGraphLink("depends_on", "dependent", "prerequisite"),
    )
    receipt_digests: set[str] = set()
    generation_digests: set[tuple[str, str]] = set()

    for object_order in permutations(objects):
        for legacy_order in permutations(legacy_links):
            for aligned_order in permutations(aligned_links):
                legacy = _generation(
                    "legacy-property",
                    PRIOR_RELEASE,
                    object_order,
                    legacy_order,
                )
                aligned = _generation(
                    "aligned-property",
                    ALIGNED_RELEASE,
                    tuple(reversed(object_order)),
                    aligned_order,
                )
                receipt = compare_graph_generations(
                    legacy,
                    aligned,
                    migration_revision="20260808_0078",
                    rebuild_pointer=POINTER,
                )
                generation_digests.add((legacy.generation_digest, aligned.generation_digest))
                receipt_digests.add(receipt.receipt_digest)

    assert len(generation_digests) == 1
    assert len(receipt_digests) == 1


def test_incomplete_missing_or_unverified_inputs_require_review() -> None:
    legacy = _generation(
        "legacy-incomplete",
        PRIOR_RELEASE,
        ("known",),
        (DirectionGraphLink("contains", "known", "missing"),),
        complete=False,
        truncated=True,
    )
    aligned = _generation(
        "aligned-complete",
        ALIGNED_RELEASE,
        ("known", "missing"),
        (DirectionGraphLink("contains", "known", "missing"),),
    )

    receipt = compare_graph_generations(
        legacy,
        aligned,
        migration_revision="20260808_0078",
        rebuild_pointer=POINTER,
    )

    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert set(receipt.review_reasons) == {
        ReviewReason.LEGACY_GENERATION_INCOMPLETE,
        ReviewReason.LEGACY_GENERATION_TRUNCATED,
        ReviewReason.LEGACY_MISSING_ENDPOINT,
        ReviewReason.LEGACY_LINK_EVIDENCE_UNVERIFIED,
        ReviewReason.ALIGNED_LINK_EVIDENCE_UNVERIFIED,
    }


def test_unbound_historical_release_remains_replayable_and_requires_review() -> None:
    legacy = DirectionGraphGeneration.create(
        generation_ref="legacy-unbound",
        ontology_release_digest=None,
        object_ids=("parent", "child"),
        links=(),
        complete=True,
    )
    aligned = _generation(
        "aligned-bound",
        ALIGNED_RELEASE,
        ("parent", "child"),
        (),
    )

    receipt = compare_graph_generations(
        legacy,
        aligned,
        migration_revision="20260808_0078",
        rebuild_pointer=POINTER,
    )

    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert receipt.review_reasons == (ReviewReason.LEGACY_RELEASE_UNBOUND,)
    assert receipt.prior_release_digest is None
    assert receipt.migration_ready is False
    assert replay_matches(receipt, legacy, aligned)


def test_unbound_aligned_release_requires_review() -> None:
    legacy = _generation("legacy-bound", PRIOR_RELEASE, (), ())
    aligned = _generation("aligned-unbound", None, (), ())

    receipt = compare_graph_generations(
        legacy,
        aligned,
        migration_revision="20260808_0078",
        rebuild_pointer=POINTER,
    )

    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert receipt.review_reasons == (ReviewReason.ALIGNED_RELEASE_UNBOUND,)
    assert receipt.aligned_release_digest is None


def test_equal_bounded_traversal_truncation_still_requires_review() -> None:
    links = (
        DirectionGraphLink("contains", "root", "child"),
        DirectionGraphLink("contains", "child", "grandchild"),
    )
    generation = _generation(
        "shared-generation",
        PRIOR_RELEASE,
        ("root", "child", "grandchild"),
        links,
    )

    receipt = compare_graph_generations(
        generation,
        generation,
        migration_revision="20260808_0078",
        rebuild_pointer=POINTER,
        bounds=ComparisonBounds(traversal_depth=1, blast_radius_depth=1),
    )

    assert receipt.disposition is ComparisonDisposition.REVIEW_REQUIRED
    assert ReviewReason.COMPARISON_TRUNCATED in receipt.review_reasons
    assert any(item.legacy_truncated for item in receipt.directional_query_deltas)
