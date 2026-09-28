"""Concept selection presents complete catalogs in shards and accepts only presented ids."""

from __future__ import annotations

from typing import Any

import pytest
from fdai.core.conversation.semantic_reasoning_concepts import (
    ConceptCandidate,
    ConceptOutcome,
    ConceptShard,
    concept_catalogs,
    select_concepts,
    shard_catalog,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain

from tests.conversation.semantic_reasoning_support import admitted, production_manifest, span

_UTTERANCE = "List the VMs and the AKS clusters"


def _admission() -> Any:
    return admitted(
        {
            "mentions": [
                {
                    "id": "m1",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(_UTTERANCE, "VMs"),
                },
                {
                    "id": "m2",
                    "form": "concept",
                    "domain": "resource_type",
                    "span": span(_UTTERANCE, "AKS clusters"),
                },
            ],
            "goals": [
                {
                    "id": goal_id,
                    "level": "instance",
                    "operation": "select",
                    "subject": mention_id,
                    "subject_scope": "collection",
                    "cue": span(_UTTERANCE, "List"),
                    "confidence": 0.9,
                }
                for goal_id, mention_id in (("g1", "m1"), ("g2", "m2"))
            ],
        },
        _UTTERANCE,
    )


def _chooser(picks: dict[str, list[str]], calls: list[ConceptShard]) -> Any:
    def choose(
        _utterance: str, mentions: tuple[dict[str, Any], ...], shard: ConceptShard
    ) -> dict[str, Any]:
        calls.append(shard)
        present = {candidate.id for candidate in shard.candidates}
        return {
            "shard_digest": shard.digest,
            "choices": [
                {
                    "mention": item["mention"],
                    "candidate_ids": [
                        pick for pick in picks.get(item["mention"], []) if pick in present
                    ],
                }
                for item in mentions
            ],
        }

    return choose


def test_every_candidate_is_presented_exactly_once_across_shards() -> None:
    catalog = concept_catalogs(production_manifest().descriptors)[MentionDomain.RESOURCE_TYPE]
    shards = shard_catalog(MentionDomain.RESOURCE_TYPE, catalog, max_bytes=2048)
    presented = [candidate.id for shard in shards for candidate in shard.candidates]

    assert len(shards) > 1
    assert sorted(presented) == sorted(candidate.id for candidate in catalog)
    assert len(presented) == len(set(presented))
    assert {shard.total for shard in shards} == {len(shards)}


def test_selection_accepts_shard_choices_and_proves_full_presentation() -> None:
    calls: list[ConceptShard] = []
    catalog = concept_catalogs(production_manifest().descriptors)
    vm = next(
        item.id
        for item in catalog[MentionDomain.RESOURCE_TYPE]
        if "compute.vm" in item.values and len(item.values) == 1
    )
    aks = next(
        item.id
        for item in catalog[MentionDomain.RESOURCE_TYPE]
        if item.values == ("kubernetes-cluster",)
    )
    receipt = select_concepts(
        _admission(),
        catalogs=catalog,
        choose=_chooser({"m1": [vm], "m2": [aks]}, calls),
        utterance=_UTTERANCE,
        max_model_calls=16,
        max_shard_bytes=4096,
    )

    assert [binding.outcome for binding in receipt.bindings] == [ConceptOutcome.ACCEPTED] * 2
    assert receipt.binding("m1").values == ("compute.vm",)  # type: ignore[union-attr]
    assert receipt.binding("m2").values == ("kubernetes-cluster",)  # type: ignore[union-attr]
    presented, total = receipt.presented[MentionDomain.RESOURCE_TYPE.value]
    assert presented == total == len(catalog[MentionDomain.RESOURCE_TYPE])
    assert receipt.model_calls == len(calls) > 1


@pytest.mark.parametrize(
    ("proposal", "reason"),
    (
        (lambda shard: {"shard_digest": "sha256:" + "0" * 64, "choices": []}, "digest"),
        (
            lambda shard: {
                "shard_digest": shard.digest,
                "choices": [
                    {"mention": "m1", "candidate_ids": ["value:not-presented"]},
                    {"mention": "m2", "candidate_ids": []},
                ],
            },
            "unpresented",
        ),
        (
            lambda shard: {
                "shard_digest": shard.digest,
                "choices": [{"mention": "m1", "candidate_ids": []}],
            },
            "missing mention",
        ),
        (lambda shard: None, "model unavailable"),
    ),
)
def test_invalid_shard_answers_never_bind_a_concept(proposal: Any, reason: str) -> None:
    receipt = select_concepts(
        _admission(),
        catalogs=concept_catalogs(production_manifest().descriptors),
        choose=lambda _utterance, _mentions, shard: proposal(shard),
        utterance=_UTTERANCE,
        max_model_calls=16,
    )

    assert {binding.outcome for binding in receipt.bindings} == {ConceptOutcome.UNAVAILABLE}, reason
    assert {binding.reason for binding in receipt.bindings} == {"concept_selection_invalid"}


def test_distinct_candidates_are_ambiguous_and_no_choice_is_not_found() -> None:
    candidates = (
        ConceptCandidate("group:database", ("mysql-server", "sql-database"), ("database",)),
        ConceptCandidate("value:sql-database", ("sql-database",)),
    )
    receipt = select_concepts(
        _admission(),
        catalogs={MentionDomain.RESOURCE_TYPE: candidates},
        choose=_chooser({"m1": ["group:database", "value:sql-database"]}, []),
        utterance=_UTTERANCE,
        max_model_calls=4,
    )

    assert receipt.binding("m1").outcome is ConceptOutcome.AMBIGUOUS  # type: ignore[union-attr]
    assert receipt.binding("m2").outcome is ConceptOutcome.NOT_FOUND  # type: ignore[union-attr]


def test_oversized_candidates_fail_closed_instead_of_raising() -> None:
    receipt = select_concepts(
        _admission(),
        catalogs=concept_catalogs(production_manifest().descriptors),
        choose=_chooser({}, []),
        utterance=_UTTERANCE,
        max_model_calls=64,
        max_shard_bytes=256,
    )

    assert {binding.reason for binding in receipt.bindings} == {"concept_catalog_unshardable"}
    assert receipt.model_calls == 0


def test_budget_exhaustion_is_explicit_and_unavailable_domains_are_typed() -> None:
    catalog = concept_catalogs(production_manifest().descriptors)
    exhausted = select_concepts(
        _admission(),
        catalogs=catalog,
        choose=_chooser({}, []),
        utterance=_UTTERANCE,
        max_model_calls=1,
        max_shard_bytes=2048,
    )
    missing = select_concepts(
        _admission(),
        catalogs={},
        choose=_chooser({}, []),
        utterance=_UTTERANCE,
        max_model_calls=4,
    )

    assert {binding.reason for binding in exhausted.bindings} == {
        "concept_selection_budget_exhausted"
    }
    assert exhausted.model_calls == 0
    assert {binding.reason for binding in missing.bindings} == {
        "concept_domain_unavailable:resource_type"
    }


def test_runoff_presents_cross_shard_finalists_together() -> None:
    catalog = (
        ConceptCandidate(
            "group:governance",
            ("resource-group", "subscription"),
            ("governance resources that group, bill, and scope other cloud resources",),
        ),
        ConceptCandidate(
            "value:resource-group",
            ("resource-group",),
            ("resource group, a lifecycle container for related cloud resources",),
        ),
    )
    presented: list[tuple[str, ...]] = []

    def choose(_utterance: str, mentions: Any, shard: ConceptShard) -> dict[str, Any]:
        ids = tuple(candidate.id for candidate in shard.candidates)
        presented.append(ids)
        finalists = len(ids) == 2 and shard.total == 1
        picks = ["value:resource-group"] if finalists else list(ids)
        return {
            "shard_digest": shard.digest,
            "choices": [
                {
                    "mention": item["mention"],
                    "candidate_ids": picks if item["mention"] == "m1" else [],
                }
                for item in mentions
            ],
        }

    receipt = select_concepts(
        _admission(),
        catalogs={MentionDomain.RESOURCE_TYPE: catalog},
        choose=choose,
        utterance=_UTTERANCE,
        max_model_calls=8,
        max_shard_bytes=256,
    )

    assert len(presented) == 3
    assert presented[-1] == ("group:governance", "value:resource-group")
    assert receipt.binding("m1").values == ("resource-group",)  # type: ignore[union-attr]
    assert receipt.model_calls == 3
