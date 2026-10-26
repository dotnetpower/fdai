from __future__ import annotations

import json
from datetime import datetime

import pytest

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    LegacyNativeScopeTransitionReportedState,
    LegacyNativeScopeTransitionReceipt,
    canonical_transition_reported_state,
    regenerated_transition_receipt_digest,
    same_transition_state_fields,
    same_transition_state_semantic_inventory,
    transition_reported_state_digest,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionEntityState,
    NativeScopeTransitionReportedState,
)


def _state(timestamp: str, digest: str) -> NativeScopeTransitionReportedState:
    return NativeScopeTransitionReportedState(
        digest=digest,
        schema_revision=15,
        entities={
            "fdai-workloads": NativeScopeTransitionEntityState(
                release_id=None,
                artifact_digests=(),
                health="unknown",
            )
        },
        observed_at=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
    )


def test_legacy_millisecond_and_hub_microsecond_state_have_distinct_canonical_digests() -> None:
    hub = _state("2026-10-27T00:00:00.787619Z", "0" * 64)
    legacy_digest = transition_reported_state_digest(hub, milliseconds=True)
    authoritative_digest = transition_reported_state_digest(hub)
    local = _state("2026-10-27T00:00:00.787000Z", legacy_digest)
    source = hub.model_copy(update={"digest": legacy_digest})
    authoritative = hub.model_copy(update={"digest": authoritative_digest})

    assert legacy_digest == "a2e334cf8b9ccee724e5dc7cc48424dd6e5de0a4e62130bc44ee9508e1aea15b"
    assert (
        authoritative_digest == "8fd409eca5356406248c1ac6063c0daf8c31da1a1e00291f9d89862fe19ffa47"
    )
    assert same_transition_state_fields(local, source)
    assert same_transition_state_fields(source, authoritative)
    assert source.observed_at - local.observed_at < datetime.resolution * 1000


def test_exact_live_receipt_preserves_immutable_and_regenerated_digests() -> None:
    receipt = LegacyNativeScopeTransitionReceipt.model_validate(
        {
            "schema_version": "fdai.lifecycle-native-transition-receipt.v1",
            "request_digest": (
                "sha256:50ff7151b77c8caf798aecfeddfa5e0ba483d5d3eebcd457f5c6d5be1b923c3c"
            ),
            "hub_approval_digest": (
                "sha256:982e6855ebfe71a181f9670f815af36d97fa85177b46be35981b2105532ad3f2"
            ),
            "installation_id": "installation-fdai-dev-wus3",
            "old_entity_id": "operator-hub-canary",
            "new_entity_id": "fdai-workloads",
            "old_scope_digest": (
                "sha256:cd55fa30684cbc0fd41510801f7ebfce86f0ca1920c13d7628fa40b1027f35e2"
            ),
            "new_scope_digest": (
                "sha256:ae6de3ca13961df13d67598caf19b21264fdfa1d6b1bce0269ac2374c22c072c"
            ),
            "old_reported_state_digest": (
                "575e1cb97a8925aff24d4f6e908a91abc4680511f62bb12453b632ec5ab6aafc"
            ),
            "new_reported_state_digest": (
                "607467ac39f2b850df618896e0e8e65e96c61b59df0821812ca4ce6f619182eb"
            ),
            "ownership_claim_digest": (
                "sha256:416a9c50ebe7b21ee9a43cf47d5a2d9a4d2dff8e61ae52675784bd68006bf30f"
            ),
            "recovery_request_digest": (
                "sha256:83f30788afec202ba879d073e9f4af8cbf0fd9e0b83950f78455d3c6d96dd64a"
            ),
            "existing_resources_digest": (
                "sha256:3d77eb510a685392612a41eebd147513a2ae1ae662a610b116a5cd5d5ba5b44f"
            ),
            "rollback_record_digest": (
                "sha256:a8ad890bdc8e6fb20c9f588550788339740b2c3b1d79714a2814663d6d7166e3"
            ),
            "completed_at": "2026-10-26T14:32:49.787619+00:00",
            "record_digest": (
                "sha256:95eeeeeaf0899c66d5e927d71d9d9b2b84bdadda7113bac95b175da3db720a69"
            ),
        }
    )
    state = LegacyNativeScopeTransitionReportedState(
        digest="607467ac39f2b850df618896e0e8e65e96c61b59df0821812ca4ce6f619182eb",
        schema_revision=0,
        entities={
            "fdai-workloads": NativeScopeTransitionEntityState(
                release_id=None,
                artifact_digests=(),
                health="unknown",
            )
        },
        observed_at=datetime.fromisoformat("2026-10-26T14:32:49.787000+00:00"),
        available_artifact_digests=(
            "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc",
            "sha256:3fb1717f3b1c034a6aca04802695d3dda6258895cd1b550d1c48db9d0b25c08f",
            "sha256:7d446ca2cf9e57ca471ebdb2b6ef0dee65bf51a2d452bfc05aebfd9a16b2c7c1",
            "sha256:8237c0f4271fe3319f7b6ef9ced407e94ddc4476a36669a61fede0cae7a3dcda",
            "sha256:824c8bf1be0d793bad8f88facbca9871b2e7d5076e1d7ddb8bcbad001d73ce31",
            "sha256:9e4343268c6a13422409998e18200f2162979949eebed79949949c3cfc18b659",
        ),
    )

    full_precision_digest = transition_reported_state_digest(
        state,
        observed_at=receipt.completed_at,
    )

    serialized_state = state.model_dump_json()
    assert transition_reported_state_digest(state, milliseconds=True) == state.digest
    assert json.loads(serialized_state)["observed_at"] == "2026-10-26T14:32:49.787Z"
    assert LegacyNativeScopeTransitionReportedState.model_validate_json(serialized_state) == state
    assert (
        full_precision_digest == "56fc0a52baf79eee894f942456cd1d5d3203f32141e6e7cb0ab8069e74b1a472"
    )
    assert (
        regenerated_transition_receipt_digest(
            receipt,
            new_reported_state_digest=full_precision_digest,
        )
        == "sha256:6b1a3839fdc4caf6a8214219a483ab69a085c2b54c7b5fdbe4e5fba48d1e6452"
    )


def _legacy_state(
    artifacts: tuple[str, ...],
    *,
    health: str = "unknown",
    digest: str | None = None,
) -> LegacyNativeScopeTransitionReportedState:
    document = {
        "schema_revision": 0,
        "entities": {
            "fdai-workloads": {
                "release_id": None,
                "artifact_digests": [],
                "health": health,
            }
        },
        "observed_at": "2026-10-26T14:32:49.787619Z",
        "available_artifact_digests": list(artifacts),
    }
    return LegacyNativeScopeTransitionReportedState.model_validate_json(
        json.dumps(
            {
                "digest": digest or canonical_digest(document),
                **document,
            }
        )
    )


def test_legacy_state_preserves_exact_live_artifact_order_and_duplicates() -> None:
    first = "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc"
    second = "sha256:3fb1717f3b1c034a6aca04802695d3dda6258895cd1b550d1c48db9d0b25c08f"
    stored = (second, first, second)

    source = _legacy_state(stored)
    target = canonical_transition_reported_state(source)

    assert source.available_artifact_digests == stored
    assert source.digest == transition_reported_state_digest(source)
    assert target.available_artifact_digests == (first, second)
    assert target.digest == transition_reported_state_digest(target)
    assert source.digest != target.digest
    assert same_transition_state_semantic_inventory(source, target)


def test_legacy_state_requires_exact_stored_digest() -> None:
    artifact = "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc"

    with pytest.raises(ValueError, match="reported state digest is invalid"):
        _legacy_state((artifact, artifact), digest="f" * 64)


def test_legacy_state_equivalence_distinguishes_multiset_and_non_artifact_fields() -> None:
    first = "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc"
    second = "sha256:3fb1717f3b1c034a6aca04802695d3dda6258895cd1b550d1c48db9d0b25c08f"
    source = _legacy_state((second, first, second))
    reordered = _legacy_state((first, second, second))
    missing_duplicate = _legacy_state((first, second))
    changed_health = _legacy_state((second, first, second), health="degraded")

    assert same_transition_state_fields(source, reordered)
    assert not same_transition_state_fields(source, missing_duplicate)
    assert not same_transition_state_fields(source, changed_health)
    assert same_transition_state_semantic_inventory(source, missing_duplicate)
    assert not same_transition_state_semantic_inventory(source, changed_health)


def test_strict_reconciliation_target_rejects_unsorted_artifacts() -> None:
    first = "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc"
    second = "sha256:3fb1717f3b1c034a6aca04802695d3dda6258895cd1b550d1c48db9d0b25c08f"

    with pytest.raises(ValueError, match="unique and sorted"):
        NativeScopeTransitionReportedState(
            digest="f" * 64,
            schema_revision=0,
            entities={
                "fdai-workloads": NativeScopeTransitionEntityState(
                    release_id=None,
                    artifact_digests=(),
                    health="unknown",
                )
            },
            observed_at=datetime.fromisoformat("2026-10-26T14:32:49.787619+00:00"),
            available_artifact_digests=(second, first),
        )
