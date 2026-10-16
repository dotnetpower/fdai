from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.rule_activation.cohort import (
    LocalRuleActivationCohortCommitStore,
    RuleCohortConflictError,
    StateStoreRuleActivationCohort,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.rule_activation_cohort import (
    RuleReplicaAcknowledgementV2,
    RuleReplicaAppliedV2,
    RuleReplicaDepartureKind,
    RuleReplicaDisposition,
    RuleReplicaIdentity,
    build_rule_cohort_prepare_v2,
    build_rule_replica_departure_evidence,
    rule_replica_acknowledgement_digest,
)
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _fixture() -> tuple[object, tuple[RuleReplicaIdentity, ...]]:
    members = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            revision_digest="sha256:" + ("a" * 64),
        ),
    )
    context = build_rule_activation_identity_context_v2(
        catalog_revisions=members,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=members,
    )
    replicas = tuple(
        RuleReplicaIdentity(
            replica_id=f"replica-{suffix}",
            principal_id=f"principal-{suffix}",
            release_id="release-1",
            startup_epoch=f"epoch-{suffix}",
            serving_lease_id=f"lease-{suffix}",
            serving_lease_expires_at=NOW + timedelta(minutes=10),
        )
        for suffix in ("a", "b")
    )
    cohort = build_rule_cohort_prepare_v2(
        generation=context.generation,
        serving_inventory_digest="sha256:" + ("f" * 64),
        revision_registry_root="sha256:" + ("b" * 64),
        catalog_manifest_digest=context.catalog_manifest.manifest_digest,
        replicas=replicas,
        prepared_at=NOW,
    )
    return cohort, replicas


def _ack(
    cohort: object,
    replica: RuleReplicaIdentity,
    *,
    disposition: RuleReplicaDisposition = RuleReplicaDisposition.ACKNOWLEDGED,
) -> RuleReplicaAcknowledgementV2:
    values = {
        "prepare_digest": cohort.prepare_digest,
        "replica_id": replica.replica_id,
        "principal_id": replica.principal_id,
        "release_id": replica.release_id,
        "startup_epoch": replica.startup_epoch,
        "serving_lease_id": replica.serving_lease_id,
        "revision_registry_root": cohort.revision_registry_root,
        "catalog_manifest_digest": cohort.catalog_manifest_digest,
        "profile_snapshot_digest": cohort.generation.profile_snapshot_digest,
        "generation_digest": cohort.generation.generation_digest,
        "supported_read_schema_versions": ("1.0.0", "2.0.0"),
        "write_schema_version": "1.0.0",
        "disposition": disposition,
        "reason": "verified" if disposition is RuleReplicaDisposition.ACKNOWLEDGED else "drift",
        "authentication_receipt_digest": "sha256:" + ("c" * 64),
        "observed_at": NOW + timedelta(seconds=1),
    }
    return RuleReplicaAcknowledgementV2(
        **values,
        acknowledgement_digest=rule_replica_acknowledgement_digest(**values),
    )


async def _prepare(
    ledger: StateStoreRuleActivationCohort,
    cohort: object,
    *,
    now: datetime = NOW,
    expected_revision: int = 0,
    verified_departure_digests: tuple[str, ...] = (),
) -> None:
    await ledger.prepare(
        cohort,
        now=now,
        expected_revision=expected_revision,
        authenticated_serving_inventory_digest=cohort.serving_inventory_digest,
        authenticated_replicas=cohort.replicas,
        verified_departure_digests=verified_departure_digests,
    )


async def test_complete_cohort_selects_candidate_and_records_applied() -> None:
    cohort, replicas = _fixture()
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationCohort(
        store=store,
        commit_store=LocalRuleActivationCohortCommitStore(
            store=store,
            clock=lambda: NOW + timedelta(seconds=4),
        ),
    )
    await _prepare(ledger, cohort)
    for replica in replicas:
        acknowledgement = _ack(cohort, replica)
        await ledger.acknowledge(
            acknowledgement,
            authenticated_identity=replica,
            authentication_receipt_digest=acknowledgement.authentication_receipt_digest,
            now=NOW + timedelta(seconds=1),
        )

    candidate = await ledger.activate_candidate(
        cohort.prepare_digest,
        now=NOW + timedelta(seconds=2),
        expected_revision=0,
    )
    assert await ledger.admit_replica(
        prepare_digest=cohort.prepare_digest,
        replica_id=replicas[0].replica_id,
        serving_lease_id=replicas[0].serving_lease_id,
        now=NOW + timedelta(seconds=2),
    )
    await ledger.record_applied(
        RuleReplicaAppliedV2(
            prepare_digest=cohort.prepare_digest,
            acknowledgement_set_digest=candidate.acknowledgement_set_digest,
            replica_id=replicas[0].replica_id,
            principal_id=replicas[0].principal_id,
            release_id=replicas[0].release_id,
            startup_epoch=replicas[0].startup_epoch,
            serving_lease_id=replicas[0].serving_lease_id,
            generation_digest=cohort.generation.generation_digest,
            applied_at=NOW + timedelta(seconds=3),
        ),
        authenticated_identity=replicas[0],
    )
    assert candidate.activation_authority is False


async def test_incomplete_refused_or_expired_cohort_cannot_activate() -> None:
    cohort, replicas = _fixture()
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationCohort(
        store=store,
        commit_store=LocalRuleActivationCohortCommitStore(
            store=store,
            clock=lambda: NOW + timedelta(seconds=2),
        ),
    )
    await _prepare(ledger, cohort)
    first = _ack(cohort, replicas[0])
    await ledger.acknowledge(
        first,
        authenticated_identity=replicas[0],
        authentication_receipt_digest=first.authentication_receipt_digest,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(RuleCohortConflictError, match="incomplete"):
        await ledger.activate_candidate(
            cohort.prepare_digest,
            now=NOW + timedelta(seconds=2),
            expected_revision=0,
        )

    refusal = _ack(cohort, replicas[1], disposition=RuleReplicaDisposition.REFUSED)
    await ledger.acknowledge(
        refusal,
        authenticated_identity=replicas[1],
        authentication_receipt_digest=refusal.authentication_receipt_digest,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(RuleCohortConflictError, match="refusal"):
        await ledger.activate_candidate(
            cohort.prepare_digest,
            now=NOW + timedelta(seconds=2),
            expected_revision=0,
        )
    with pytest.raises(ValueError, match="timezone"):
        await ledger.activate_candidate(
            cohort.prepare_digest,
            now=datetime(2026, 10, 17),
            expected_revision=0,
        )


async def test_acknowledgement_requires_authenticated_frozen_identity() -> None:
    cohort, replicas = _fixture()
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationCohort(
        store=store,
        commit_store=LocalRuleActivationCohortCommitStore(store=store),
    )
    await _prepare(ledger, cohort)

    with pytest.raises(RuleCohortConflictError, match="identity mismatch"):
        await ledger.acknowledge(
            _ack(cohort, replicas[0]),
            authenticated_identity=replicas[0].model_copy(
                update={"principal_id": "another-principal"}
            ),
            authentication_receipt_digest="sha256:" + ("c" * 64),
            now=NOW + timedelta(seconds=1),
        )


async def test_successor_cohort_requires_departure_evidence_for_removed_replica() -> None:
    cohort, replicas = _fixture()
    store = InMemoryStateStore()
    ledger = StateStoreRuleActivationCohort(
        store=store,
        commit_store=LocalRuleActivationCohortCommitStore(store=store),
    )
    await _prepare(ledger, cohort)
    successor_without_evidence = build_rule_cohort_prepare_v2(
        generation=cohort.generation,
        predecessor_prepare_digest=cohort.prepare_digest,
        serving_inventory_digest="sha256:" + ("1" * 64),
        revision_registry_root=cohort.revision_registry_root,
        catalog_manifest_digest=cohort.catalog_manifest_digest,
        replicas=(replicas[0],),
        prepared_at=NOW + timedelta(seconds=5),
    )

    with pytest.raises(RuleCohortConflictError, match="departure evidence"):
        await _prepare(
            ledger,
            successor_without_evidence,
            now=NOW + timedelta(seconds=5),
            expected_revision=1,
        )

    successor = build_rule_cohort_prepare_v2(
        generation=cohort.generation,
        predecessor_prepare_digest=cohort.prepare_digest,
        serving_inventory_digest="sha256:" + ("1" * 64),
        revision_registry_root=cohort.revision_registry_root,
        catalog_manifest_digest=cohort.catalog_manifest_digest,
        replicas=(replicas[0],),
        departures=(
            build_rule_replica_departure_evidence(
                replica=replicas[1],
                kind=RuleReplicaDepartureKind.DRAINED,
                serving_inventory_digest=cohort.serving_inventory_digest,
                authentication_receipt_digest="sha256:" + ("2" * 64),
                observed_at=NOW + timedelta(seconds=4),
            ),
        ),
        prepared_at=NOW + timedelta(seconds=5),
    )

    await _prepare(
        ledger,
        successor,
        now=NOW + timedelta(seconds=5),
        expected_revision=1,
        verified_departure_digests=(successor.departures[0].evidence_digest,),
    )
