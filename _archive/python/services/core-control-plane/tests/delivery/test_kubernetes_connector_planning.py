"""Private-cluster recommendations never infer missing access or authorize installation."""

from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
from fdai_service_contracts.observer_deployment import ConstraintName, ObserverDeploymentContext

NOW = datetime(2026, 9, 19, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def context(*, states=None, **changes):
    states = states or {}
    return ObserverDeploymentContext.model_validate(
        {
            "target_ref": "cluster-example",
            "discovery_digest": DIGEST,
            "observed_at": NOW,
            "expires_at": NOW + timedelta(minutes=10),
            "private_cluster": True,
            "facts": [
                {
                    "target_ref": "cluster-example",
                    "name": name,
                    "state": states.get(name, "allowed"),
                    "source": "operator_review",
                    "evidence_digest": DIGEST,
                    "observed_at": NOW,
                    "expires_at": NOW + timedelta(minutes=5),
                }
                for name in get_args(ConstraintName)
            ],
            **changes,
        }
    )


def test_prefers_existing_gitops_and_private_egress_without_authority() -> None:
    proposal = propose_observer_deployment(context(), now=NOW)
    assert proposal.status == "ready_for_review"
    assert proposal.recommended.method == "gitops"
    assert proposal.recommended.egress == "private"
    assert proposal.execution_authority is False
    assert proposal.approval_required is True


def test_excludes_denied_paths_before_ranking() -> None:
    proposal = propose_observer_deployment(
        context(states={"gitops_authorized": "denied", "private_egress": "denied"}), now=NOW
    )
    assert proposal.recommended.method == "existing_host"
    assert proposal.recommended.egress == "public"


@pytest.mark.parametrize(
    "name",
    [
        "azure_policy",
        "kubernetes_read",
        "admission",
        "capacity",
        "artifact_verified",
        "persistent_storage",
        "mtls_gateway",
        "ownership_known",
    ],
)
def test_unknown_hard_gate_never_recommends(name) -> None:
    proposal = propose_observer_deployment(context(states={name: "unknown"}), now=NOW)
    assert proposal.status == "needs_evidence"
    assert proposal.recommended is None


@pytest.mark.parametrize(
    "name", ["persistent_storage", "kubernetes_read", "mtls_gateway", "azure_policy"]
)
def test_denied_requirement_has_no_unsupported_fallback(name) -> None:
    proposal = propose_observer_deployment(context(states={name: "denied"}), now=NOW)
    assert proposal.status == "blocked"
    assert proposal.recommended is None


def test_existing_owner_and_operator_pin_cannot_be_overridden() -> None:
    assert (
        propose_observer_deployment(
            context(existing_method="existing_host"), now=NOW
        ).recommended.method
        == "existing_host"
    )
    assert (
        propose_observer_deployment(
            context(existing_method="existing_host", requested_method="gitops"), now=NOW
        ).status
        == "blocked"
    )
    assert (
        propose_observer_deployment(
            context(requested_method="run_command"), now=NOW
        ).recommended.method
        == "run_command"
    )


def test_stale_fact_is_unknown_and_expired_context_rejected() -> None:
    inputs = context()
    assert (
        propose_observer_deployment(inputs, now=NOW + timedelta(minutes=5)).status
        == "needs_evidence"
    )
    with pytest.raises(ValueError):
        propose_observer_deployment(inputs, now=NOW + timedelta(minutes=10))


def test_private_detection_must_be_boolean_and_false_has_no_candidates() -> None:
    assert (
        propose_observer_deployment(context(private_cluster=False), now=NOW).status
        == "not_applicable"
    )
    with pytest.raises(ValueError):
        context(private_cluster="true")


def test_constraint_order_does_not_change_proposal_identity() -> None:
    inputs = context()
    reversed_context = context(facts=tuple(reversed(inputs.facts)))
    assert propose_observer_deployment(inputs, now=NOW) == propose_observer_deployment(
        reversed_context, now=NOW
    )


def test_generated_boundary_contracts_validate_recommendations() -> None:
    from fdai_service_contracts.schema import (
        JsonSchemaContractValidator,
        PackageResourceSchemaRegistry,
    )

    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    inputs = context()
    validator.validate("observer-deployment-context", inputs.model_dump(mode="json"))
    validator.validate(
        "observer-deployment-proposal",
        propose_observer_deployment(inputs, now=NOW).model_dump(mode="json"),
    )


@pytest.mark.parametrize(
    "change", ["authority", "duplicate", "incomplete", "contradiction", "expiry", "extra"]
)
def test_semantic_boundary_rejects_corrupt_proposals_even_with_new_digest(change) -> None:
    from fdai_service_contracts.compatibility import canonical_digest
    from fdai_service_contracts.schema import (
        ContractValidationError,
        JsonSchemaContractValidator,
        PackageResourceSchemaRegistry,
    )

    value = propose_observer_deployment(context(), now=NOW).model_dump(mode="json")
    if change == "authority":
        value["execution_authority"] = True
    elif change == "duplicate":
        value["candidates"][1] = value["candidates"][0]
    elif change == "incomplete":
        value["candidates"].pop()
    elif change == "contradiction":
        value["candidates"][0]["blockers"] = ["azure_policy"]
    elif change == "expiry":
        value["expires_at"] = (NOW + timedelta(hours=2)).isoformat()
    else:
        value["execute"] = True
    value["proposal_digest"] = canonical_digest(
        {key: item for key, item in value.items() if key != "proposal_digest"}
    )
    with pytest.raises(ContractValidationError):
        JsonSchemaContractValidator(PackageResourceSchemaRegistry()).validate(
            "observer-deployment-proposal", value
        )
