"""Concept selection presents complete catalogs in shards and accepts only presented ids."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml
from fdai.core.conversation.semantic_manifest import (
    CatalogQueryManifestProvider,
    ConceptVocabularies,
)
from fdai.core.conversation.semantic_reasoning_concepts import (
    ConceptBinding,
    ConceptCandidate,
    ConceptOutcome,
    ConceptSelectionReceipt,
    ConceptShard,
    agree_concepts,
    concept_catalogs,
    select_concepts,
    shard_catalog,
)
from fdai.core.conversation.semantic_reasoning_form import MentionDomain
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.resource_health_values import resource_health_state_values
from fdai.rule_catalog.schema.inventory_query_language import (
    load_inventory_query_language_from_mapping,
)
from fdai.shared.ontology.release import build_ontology_release

from tests.conversation.semantic_reasoning_support import (
    ROOT,
    admitted,
    production_catalog,
    production_manifest,
    span,
)

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
        (
            lambda shard: {
                "shard_digest": shard.digest,
                "choices": [{"mention": ["m1"], "candidate_ids": []}],
            },
            "unhashable mention",
        ),
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


def test_complete_prompt_shards_fit_the_actual_transmitted_byte_limit() -> None:
    catalog = tuple(
        ConceptCandidate(f"value:example.{index}", (f"example.{index}",), ("Example type",))
        for index in range(20)
    )
    shards = shard_catalog(MentionDomain.RESOURCE_TYPE, catalog, max_bytes=400)
    assert len(shards) > 1
    assert tuple(item for shard in shards for item in shard.candidates) == catalog
    assert all(
        len(json.dumps(shard.prompt_payload(), ensure_ascii=False, separators=(",", ":")).encode())
        <= 400
        for shard in shards
    )


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
        max_shard_bytes=400,
    )

    assert len(presented) == 3
    assert presented[-1] == ("group:governance", "value:resource-group")
    assert receipt.binding("m1").values == ("resource-group",)  # type: ignore[union-attr]
    assert receipt.model_calls == 3


def test_runoff_cannot_bind_another_mentions_finalist() -> None:
    catalog = (
        ConceptCandidate("group:compute", ("compute.vm", "compute.vm-scale-set"), ("compute",)),
        ConceptCandidate("group:database", ("mysql-server", "sql-database"), ("database",)),
        ConceptCandidate("value:compute.vm", ("compute.vm",), ("virtual machine",)),
        ConceptCandidate("value:sql-database", ("sql-database",), ("sql database",)),
    )
    picks = {
        "m1": ["group:compute", "value:compute.vm"],
        "m2": ["group:database", "value:sql-database"],
    }

    def choose(_utterance: str, mentions: Any, shard: ConceptShard) -> dict[str, Any]:
        runoff = shard.total == 1 and len(shard.candidates) == 4
        present = {candidate.id for candidate in shard.candidates}
        swapped = {"m1": ["group:database"], "m2": ["value:compute.vm"]}
        return {
            "shard_digest": shard.digest,
            "choices": [
                {
                    "mention": item["mention"],
                    "candidate_ids": (
                        swapped[item["mention"]]
                        if runoff
                        else [pick for pick in picks[item["mention"]] if pick in present]
                    ),
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
        max_shard_bytes=400,
    )

    assert {binding.outcome for binding in receipt.bindings} == {ConceptOutcome.AMBIGUOUS}


def test_every_declared_type_is_selectable_on_its_own() -> None:
    catalog = concept_catalogs(production_manifest().descriptors)[MentionDomain.RESOURCE_TYPE]
    exact = {item.values[0] for item in catalog if len(item.values) == 1}
    declared = {value for item in catalog for value in item.values}

    assert declared <= exact


def _bound(mention_id: str, *values: str, candidates: tuple[str, ...] = ()) -> ConceptBinding:
    return ConceptBinding(
        mention_id,
        MentionDomain.RESOURCE_TYPE,
        ConceptOutcome.ACCEPTED,
        candidate_ids=candidates or tuple(f"value:{value}" for value in values),
        values=values,
    )


def _receipt(*bindings: ConceptBinding, calls: int = 1) -> ConceptSelectionReceipt:
    return ConceptSelectionReceipt(bindings=bindings, model_calls=calls)


def test_two_blind_choosers_bind_only_the_values_they_agree_on() -> None:
    same = _bound("m1", "compute.vm")
    through_group = _bound("m1", "compute.vm", candidates=("group:compute.vm",))
    general = _bound("m1")
    missing = ConceptBinding("m1", MentionDomain.RESOURCE_TYPE, ConceptOutcome.NOT_FOUND)

    agreed = agree_concepts(_receipt(same), _receipt(through_group, calls=2))
    differing = agree_concepts(_receipt(same), _receipt(_bound("m1", "network.subnet")))
    widened = agree_concepts(_receipt(general), _receipt(_bound("m1", "network.subnet")))
    one_sided = agree_concepts(_receipt(same), _receipt(missing))
    unanswered = agree_concepts(_receipt(same), _receipt())
    neither = agree_concepts(_receipt(missing), _receipt(missing))

    assert agreed.bindings == (same,) and agreed.model_calls == 3
    for receipt in (differing, widened, one_sided, unanswered):
        (binding,) = receipt.bindings
        assert binding.outcome is ConceptOutcome.AMBIGUOUS
        assert binding.reason == "concept_disagreement:resource_type"
        assert binding.values == ()
    assert neither.bindings == (missing,)


def test_choosers_see_reviewed_object_type_descriptions_as_labels() -> None:
    manifest = production_manifest()
    labels = dict(manifest.object_labels)

    catalog = concept_catalogs(manifest.descriptors, object_labels=labels)[
        MentionDomain.OBJECT_TYPE
    ]
    by_value = {candidate.values[0]: candidate for candidate in catalog}

    # Resource and ResourceType differ by meaning, which each reviewed description states.
    assert labels["Resource"] and labels["ResourceType"]
    assert by_value["Resource"].labels == ("Resource", labels["Resource"])
    assert by_value["ResourceType"].labels == ("ResourceType", labels["ResourceType"])
    # The label is context only: the candidate still binds exactly its own name.
    assert by_value["Resource"].values == ("Resource",)
    # Without descriptions the catalog keeps name-only labels.
    plain = concept_catalogs(manifest.descriptors)[MentionDomain.OBJECT_TYPE]
    assert all(candidate.labels == candidate.values for candidate in plain)


def test_metric_concepts_ground_over_the_reviewed_registry_only_with_their_reader() -> None:
    labels = {"resource.cpu.utilization_pct": "Processor utilization of one Resource."}
    plain = production_manifest()
    offered = production_manifest(metric_labels=tuple(labels.items()))
    unbound = production_manifest(
        metric_labels=tuple(labels.items()), unbound=("query.resource_metric_inventory",)
    )

    catalog = concept_catalogs(offered.descriptors, metric_labels=dict(offered.metric_labels))
    (candidate,) = catalog[MentionDomain.METRIC]

    assert candidate.values == ("resource.cpu.utilization_pct",)
    assert candidate.labels == (
        "resource.cpu.utilization_pct",
        labels["resource.cpu.utilization_pct"],
    )
    # The digest binds the offered concepts, and no reader means no metric catalog.
    assert offered.manifest_digest != plain.manifest_digest
    assert unbound.metric_labels == () and MentionDomain.METRIC not in concept_catalogs(
        unbound.descriptors, metric_labels=dict(unbound.metric_labels)
    )


_HEALTH_GROUPS = (
    ("resource_health.degraded", ("degraded",)),
    ("resource_health.unavailable", ("unavailable",)),
)


def test_health_concepts_ground_over_the_reviewed_groups_only_with_their_reader() -> None:
    plain = production_manifest()
    offered = production_manifest(health_labels=_HEALTH_GROUPS)
    unbound = production_manifest(
        health_labels=_HEALTH_GROUPS, unbound=("query.resource_health_inventory",)
    )

    catalog = concept_catalogs(offered.descriptors, health_labels=dict(offered.health_labels))
    by_value = {candidate.values: candidate for candidate in catalog[MentionDomain.HEALTH]}

    # Each candidate binds exactly one reviewed concept; its provider states are labels only.
    assert set(by_value) == {("resource_health.degraded",), ("resource_health.unavailable",)}
    assert by_value[("resource_health.degraded",)].labels == (
        "resource_health.degraded",
        "degraded",
    )
    # The digest binds the offered concepts, and no reader means no health catalog.
    assert offered.manifest_digest != plain.manifest_digest
    assert unbound.health_labels == () and MentionDomain.HEALTH not in concept_catalogs(
        unbound.descriptors, health_labels=dict(unbound.health_labels)
    )


def test_the_manifest_provider_offers_the_reviewed_health_groups() -> None:
    language = load_inventory_query_language_from_mapping(
        yaml.safe_load(
            (ROOT / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    catalog = production_catalog()
    functions = operational_function_types(catalog.function_types)
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=functions,
    )
    provider = CatalogQueryManifestProvider(
        release=release,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=functions,
        bound_function_names=tuple(function.name for function in functions),
        vocabularies=ConceptVocabularies(inventory_query_language=language),
    )

    manifest = provider.manifest_for(
        principal=Principal(id="operator", role=Role.READER), purpose="operations-review"
    )

    groups = resource_health_state_values(language)
    assert groups and {key: tuple(values) for key, values in manifest.health_labels} == groups
    # Without reviewed vocabularies, no measure concept is offered.
    assert ConceptVocabularies().health_labels() == {}
    assert ConceptVocabularies().metric_labels() == {}


def test_reviewed_lifecycle_values_join_the_state_catalog_with_their_object_type() -> None:
    catalog = concept_catalogs(production_manifest().descriptors)[MentionDomain.STATE]
    lifecycle = {
        candidate.values: candidate
        for candidate in catalog
        if candidate.values[0].startswith("lifecycle:")
    }

    # Each lifecycle value names its ObjectType and property; the label says which.
    assert {
        (f"lifecycle:Incident.status={value}",)
        for value in ("closed", "mitigated", "open", "resolved", "triaging")
    } <= set(lifecycle)
    assert {values[0].split(".", 1)[0] for values in lifecycle} == {
        "lifecycle:CausalHypothesis",
        "lifecycle:Incident",
        "lifecycle:Process",
        "lifecycle:RecoveryPlan",
    }
    assert lifecycle[("lifecycle:Incident.status=open",)].labels == ("open", "Incident status")
    # Resource states stay in the same catalog, unchanged.
    assert any(candidate.values == ("resource_state.running",) for candidate in catalog)


def test_a_vocabulary_without_health_groups_offers_no_health_concepts() -> None:
    mapping = yaml.safe_load(
        (ROOT / "rule-catalog" / "vocabulary" / "inventory-query-language.yaml").read_text(
            encoding="utf-8"
        )
    )
    for state in ("not_ready", "degraded", "unavailable", "unhealthy"):
        mapping["states"].pop(state)
    language = load_inventory_query_language_from_mapping(mapping)

    # A fork without Resource Health keeps its manifest instead of failing composition.
    assert ConceptVocabularies(inventory_query_language=language).health_labels() == {}


def test_every_lifecycle_domain_pins_its_projection_enum_and_a_readable_status() -> None:
    from fdai.composition.semantic_query_value_domains import lifecycle_value_domains
    from fdai.core.rca.hypothesis import CausalHypothesisStatus
    from fdai.core.recovery.models import RecoveryPlanStatus
    from fdai.shared.contracts.models import IncidentState
    from fdai.shared.providers.process_runtime import ProcessStatus

    enums = {
        "CausalHypothesis": CausalHypothesisStatus,
        "Incident": IncidentState,
        "Process": ProcessStatus,
        "RecoveryPlan": RecoveryPlanStatus,
    }
    readable = {
        item["name"]: item.get("properties") or {}
        for item in production_manifest().descriptors
        if item.get("kind") == "object"
    }

    for domain in lifecycle_value_domains():
        # The projection writes exactly these enum values, so the domain can't drift from it.
        assert domain.values == tuple(sorted(item.value for item in enums[domain.object_type]))
        assert domain.lifecycle_state is True
        assert readable[domain.object_type]["status"]["lifecycle_state"] is True
