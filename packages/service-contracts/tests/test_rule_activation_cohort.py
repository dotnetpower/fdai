from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai_service_contracts.rule_activation_cohort import (
    RuleReplicaAcknowledgementV2,
    RuleReplicaDisposition,
    RuleReplicaIdentity,
    build_rule_cohort_prepare_v2,
    rule_acknowledgement_set_digest,
    rule_replica_acknowledgement_digest,
)
from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def _context() -> object:
    members = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            revision_digest="sha256:" + ("a" * 64),
        ),
    )
    return build_rule_activation_identity_context_v2(
        catalog_revisions=members,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=members,
    )


def _replica(replica_id: str) -> RuleReplicaIdentity:
    return RuleReplicaIdentity(
        replica_id=replica_id,
        principal_id=f"principal-{replica_id}",
        release_id="release-1",
        startup_epoch=f"epoch-{replica_id}",
        serving_lease_id=f"lease-{replica_id}",
        serving_lease_expires_at=NOW + timedelta(minutes=10),
    )


def _ack(cohort: object, replica: RuleReplicaIdentity) -> RuleReplicaAcknowledgementV2:
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
        "disposition": RuleReplicaDisposition.ACKNOWLEDGED,
        "reason": "verified",
        "authentication_receipt_digest": "sha256:" + ("c" * 64),
        "observed_at": NOW + timedelta(seconds=1),
    }
    return RuleReplicaAcknowledgementV2(
        **values,
        acknowledgement_digest=rule_replica_acknowledgement_digest(**values),
    )


def test_prepare_and_acknowledgement_set_are_canonical() -> None:
    context = _context()
    replicas = (_replica("replica-a"), _replica("replica-b"))
    cohort = build_rule_cohort_prepare_v2(
        generation=context.generation,
        serving_inventory_digest="sha256:" + ("f" * 64),
        revision_registry_root="sha256:" + ("b" * 64),
        catalog_manifest_digest=context.catalog_manifest.manifest_digest,
        replicas=replicas,
        prepared_at=NOW,
    )
    acknowledgements = tuple(_ack(cohort, replica) for replica in replicas)

    assert len(rule_acknowledgement_set_digest(acknowledgements)) == 71
    with pytest.raises(ValueError, match="unique and sorted"):
        build_rule_cohort_prepare_v2(
            generation=context.generation,
            serving_inventory_digest="sha256:" + ("f" * 64),
            revision_registry_root="sha256:" + ("b" * 64),
            catalog_manifest_digest=context.catalog_manifest.manifest_digest,
            replicas=tuple(reversed(replicas)),
            prepared_at=NOW,
        )


def test_prepare_rejects_expired_serving_lease() -> None:
    context = _context()
    expired = _replica("replica-a").model_copy(update={"serving_lease_expires_at": NOW})

    with pytest.raises(ValueError, match="outlive preparation"):
        build_rule_cohort_prepare_v2(
            generation=context.generation,
            serving_inventory_digest="sha256:" + ("f" * 64),
            revision_registry_root="sha256:" + ("b" * 64),
            catalog_manifest_digest=context.catalog_manifest.manifest_digest,
            replicas=(expired,),
            prepared_at=NOW,
        )
