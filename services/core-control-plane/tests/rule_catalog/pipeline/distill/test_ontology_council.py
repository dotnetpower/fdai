"""Consensus and claim-accounting tests for ontology council distillation."""

from __future__ import annotations

from dataclasses import replace

from fdai.rule_catalog.pipeline.distill.ontology_council import OntologyCouncilDistiller
from fdai.shared.providers.distiller import CandidateKind
from fdai.shared.providers.ontology_council import CouncilOutcome, CouncilTokenUsage

from .ontology_council_fakes import (
    LINK_TEXT,
    OBJECT_TEXT,
    CallTracker,
    context,
    document,
    link_vote,
    models,
    object_vote,
    policy,
    unsupported_vote,
)


async def test_three_of_three_object_consensus_builds_exact_candidate() -> None:
    council_models = models((object_vote, object_vote, object_vote))
    result = await OntologyCouncilDistiller(
        models=council_models,
        policy=policy(),
    ).distill_ontology(document(), context())

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind is CandidateKind.ONTOLOGY_OBJECT
    assert candidate.source_lines == (1, 1)
    assert candidate.content_sha == document().content_sha
    assert candidate.body["source_assertion"] == OBJECT_TEXT
    assert candidate.body["properties"] == {"owner_ref": "team:platform"}
    receipt = result.council_receipts[0]
    assert receipt.outcome is CouncilOutcome.CONSENSUS
    assert receipt.prompt_digest == "b" * 64
    assert receipt.schema_digest == "c" * 64
    assert receipt.ontology_release == context().ontology_release
    assert {item.publisher for item in receipt.models} == {"publisher-one"}
    assert {item.family for item in receipt.models} == {
        "family-1",
        "family-2",
        "family-3",
    }
    assert {item.version for item in receipt.models} == {"1.0.0"}
    assert {item.deployment for item in receipt.models} == {
        "deployment-1",
        "deployment-2",
        "deployment-3",
    }
    assert tuple(item.identity_digest for item in receipt.models) == receipt.model_digests
    assert tuple(item.model_digest for item in receipt.initial_invocations) == (
        receipt.model_digests
    )
    assert all(item.prompt_tokens == 0 for item in receipt.initial_invocations)
    assert all(item.completion_tokens == 0 for item in receipt.initial_invocations)
    assert all(item.latency_ms >= 0.0 for item in receipt.initial_invocations)
    assert all(model.blind_calls == 1 for model in council_models)
    assert all(model.revision_calls == 0 for model in council_models)


async def test_three_of_three_link_consensus_builds_strict_link_candidate() -> None:
    result = await OntologyCouncilDistiller(
        models=models((link_vote, link_vote, link_vote)),
        policy=policy(),
    ).distill_ontology(document(LINK_TEXT), context())

    assert result.candidates[0].kind is CandidateKind.ONTOLOGY_LINK
    assert result.candidates[0].body["from_identity"] == "service:checkout"
    assert result.candidates[0].body["to_identity"] == "service:billing"
    assert result.council_receipts[0].outcome is CouncilOutcome.CONSENSUS


async def test_two_of_three_stays_contested_after_one_revision() -> None:
    def different(packet, identity):  # type: ignore[no-untyped-def]
        return object_vote(packet, identity, target_identity="service:billing")

    council_models = models((object_vote, object_vote, different))
    result = await OntologyCouncilDistiller(
        models=council_models,
        policy=policy(),
    ).distill_ontology(document(), context())

    assert result.candidates == ()
    assert result.council_receipts[0].outcome is CouncilOutcome.CONTESTED
    assert result.council_receipts[0].rounds == 2
    assert "target_identity" in result.council_receipts[0].disputed_fields
    assert all(model.revision_calls == 1 for model in council_models)


async def test_all_unsupported_closes_without_revision_or_candidate() -> None:
    council_models = models((unsupported_vote, unsupported_vote, unsupported_vote))
    result = await OntologyCouncilDistiller(
        models=council_models,
        policy=policy(),
    ).distill_ontology(document(), context())

    assert result.candidates == ()
    assert result.council_receipts[0].outcome is CouncilOutcome.UNSUPPORTED
    assert all(model.revision_calls == 0 for model in council_models)


async def test_mixed_unsupported_and_proposals_is_contested() -> None:
    result = await OntologyCouncilDistiller(
        models=models((object_vote, object_vote, unsupported_vote)),
        policy=policy(),
    ).distill_ontology(document(), context())

    assert result.candidates == ()
    assert result.council_receipts[0].outcome is CouncilOutcome.CONTESTED


async def test_revision_starts_only_after_all_blind_votes_and_can_reach_consensus() -> None:
    tracker = CallTracker()

    def different(packet, identity):  # type: ignore[no-untyped-def]
        return object_vote(packet, identity, target_identity="service:billing")

    council_models = models(
        (object_vote, object_vote, different),
        revised=(object_vote, object_vote, object_vote),
        tracker=tracker,
        delays=(0.02, 0.01, 0.0),
    )
    result = await OntologyCouncilDistiller(
        models=council_models,
        policy=policy(),
    ).distill_ontology(document(), context())

    assert tracker.blind_completed == 3
    assert tracker.revision_started == 3
    assert len(result.candidates) == 1
    assert result.council_receipts[0].outcome is CouncilOutcome.CONSENSUS
    assert result.council_receipts[0].rounds == 2


async def test_every_claim_has_one_receipt_and_coverage_tracks_only_candidates() -> None:
    text = OBJECT_TEXT + "\nBilling service must be owned by Platform team."
    result = await OntologyCouncilDistiller(
        models=models((object_vote, object_vote, object_vote)),
        policy=policy(),
    ).distill_ontology(document(text), context())

    assert len(result.council_receipts) == 2
    assert len({receipt.claim_digest for receipt in result.council_receipts}) == 2
    assert len(result.candidates) == 2
    assert result.coverage.covered == result.coverage.total == 1


async def test_deterministic_fake_replay_is_stable() -> None:
    first = await OntologyCouncilDistiller(
        models=models((object_vote, object_vote, object_vote)),
        policy=policy(),
    ).distill_ontology(document(), context())
    second = await OntologyCouncilDistiller(
        models=models((object_vote, object_vote, object_vote)),
        policy=policy(),
    ).distill_ontology(document(), context())

    assert first == second


def test_conformance_identity_changes_with_models_prompt_and_schema() -> None:
    base_models = models((object_vote, object_vote, object_vote))
    changed_models = models((object_vote, object_vote, object_vote))
    changed_models[0].identity = replace(changed_models[0].identity, version="2.0.0")
    base_policy = policy()

    versions = {
        OntologyCouncilDistiller(
            models=base_models,
            policy=base_policy,
        )
        .distiller_capability()
        .binding_version,
        OntologyCouncilDistiller(
            models=changed_models,
            policy=base_policy,
        )
        .distiller_capability()
        .binding_version,
        OntologyCouncilDistiller(
            models=models((object_vote, object_vote, object_vote)),
            policy=replace(base_policy, prompt_digest="d" * 64),
        )
        .distiller_capability()
        .binding_version,
        OntologyCouncilDistiller(
            models=models((object_vote, object_vote, object_vote)),
            policy=replace(base_policy, schema_digest="e" * 64),
        )
        .distiller_capability()
        .binding_version,
    }

    assert len(versions) == 4


def test_provider_usage_does_not_change_vote_or_semantic_digest() -> None:
    packet_models = models((object_vote, object_vote, object_vote))
    claim_context = context()
    claim_document = document()
    from fdai.rule_catalog.pipeline.distill.ontology_claims import (
        claim_text_records,
        inventory_claims,
    )
    from fdai.rule_catalog.pipeline.distill.ontology_council_packets import (
        build_council_claim_packet,
    )

    claim = inventory_claims(claim_document)[0]
    exact_text = dict(claim_text_records(claim_document, (claim,)))[claim.claim_id]
    packet = build_council_claim_packet(claim, exact_text, claim_context)
    first = object_vote(packet, packet_models[0].identity)
    second = replace(
        first,
        usage=CouncilTokenUsage(prompt_tokens=100, completion_tokens=50),
    )

    assert first == second
    assert first.digest == second.digest
    assert first.semantic_fingerprint == second.semantic_fingerprint
