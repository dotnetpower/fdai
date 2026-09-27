#!/usr/bin/env python3
"""Private claim and receipt records for the standalone Entra operation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.identity_profile import IdentityProfileObservation
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from genesis_entra import EntraPlan

_DIGEST = re.compile(r"[0-9a-f]{64}")
_APPS = frozenset({"fdai-api", "fdai-console-spa", "fdai-approval-bot"})
_GROUPS = frozenset(
    {"aw-readers", "aw-contributors", "aw-approvers", "aw-owners", "aw-break-glass"}
)


@dataclass(frozen=True, slots=True, repr=False)
class OperationContext:
    """Private exact source, target, and executor binding."""

    source_commit: str
    executor_object_id: str = field(repr=False)
    environment: str
    target_binding: str
    target_profile_digest: str
    control_profile_digest: str
    snapshot_digest: str
    executor_digest: str
    run_binding: str


def claim_record(
    context: OperationContext,
    observation: IdentityProfileObservation,
    plan: EntraPlan,
    approval_actor_digest: str,
    approval_principal_digest: str,
    execution_actor_digest: str,
) -> dict[str, object]:
    """Build one additive, consent-free pre-effect claim."""

    if (
        execution_actor_digest != context.executor_digest
        or approval_principal_digest == execution_actor_digest
    ):
        raise ValueError("Entra-only approval and execution identities are invalid")
    plan_projection = plan.projection()
    claim: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-only-claim.v2",
        "state": "applying",
        "source_commit": context.source_commit,
        "environment": context.environment,
        "target_profile_digest": context.target_profile_digest,
        "control_profile_digest": context.control_profile_digest,
        "snapshot_digest": context.snapshot_digest,
        "run_binding": context.run_binding,
        "target_binding": context.target_binding,
        "executor_digest": context.executor_digest,
        "plan_digest": plan.digest,
        "profile_digest": observation.digest,
        "approval_actor_digest": approval_actor_digest,
        "approval_principal_digest": approval_principal_digest,
        "execution_actor_digest": execution_actor_digest,
        "approval_executor_separated": True,
        "plan": plan_projection,
        "idempotency_key": canonical_digest(
            {
                "run_binding": context.run_binding,
                "plan_digest": plan.digest,
                "profile_digest": observation.digest,
                "snapshot_digest": context.snapshot_digest,
                "approval_actor_digest": approval_actor_digest,
                "approval_principal_digest": approval_principal_digest,
                "execution_actor_digest": execution_actor_digest,
            }
        ),
        "provider_admin_consent_granted": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    claim["claim_digest"] = canonical_digest(claim)
    return claim


def write_receipt(
    *,
    receipt_path: Path,
    context: OperationContext,
    observation: IdentityProfileObservation,
    plan: object,
    plan_digest: str,
    approval_actor_digest: str,
    approval_principal_digest: str,
    execution_actor_digest: str,
    readback_digest: str,
    effects: dict[str, object],
    recovered_from_claim: bool,
) -> dict[str, object]:
    """Write one content-addressed private terminal receipt."""

    if (
        execution_actor_digest != context.executor_digest
        or approval_principal_digest == execution_actor_digest
    ):
        raise ValueError("Entra-only approval and execution identities are invalid")
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-entra-only-receipt.v2",
        "state": "applied",
        "source_commit": context.source_commit,
        "environment": context.environment,
        "target_profile_digest": context.target_profile_digest,
        "control_profile_digest": context.control_profile_digest,
        "snapshot_digest": context.snapshot_digest,
        "run_binding": context.run_binding,
        "target_binding": context.target_binding,
        "executor_digest": context.executor_digest,
        "plan_digest": plan_digest,
        "profile_digest": observation.digest,
        "approval_actor_digest": approval_actor_digest,
        "approval_principal_digest": approval_principal_digest,
        "execution_actor_digest": execution_actor_digest,
        "approval_executor_separated": True,
        "plan": plan,
        "readback_digest": readback_digest,
        "effects": effects,
        "approval_verified": True,
        "claim_recorded": True,
        "readback_verified": True,
        "provider_admin_consent_granted": False,
        "foundation_invoked": False,
        "application_invoked": False,
        "recovered_from_claim": recovered_from_claim,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        receipt_path,
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return receipt


def load_claim(
    path: Path,
    context: OperationContext,
    observation: IdentityProfileObservation,
) -> dict[str, object]:
    """Load one exact retained claim for verification-only recovery."""

    claim = _private_json(path, "Entra-only claim")
    digest = claim.pop("claim_digest", None)
    if (
        set(claim)
        != {
            "schema_version",
            "state",
            "source_commit",
            "environment",
            "target_profile_digest",
            "control_profile_digest",
            "snapshot_digest",
            "run_binding",
            "target_binding",
            "executor_digest",
            "plan_digest",
            "profile_digest",
            "approval_actor_digest",
            "approval_principal_digest",
            "execution_actor_digest",
            "approval_executor_separated",
            "plan",
            "idempotency_key",
            "provider_admin_consent_granted",
            "mutation_performed",
            "subscription_ready",
        }
        or not isinstance(digest, str)
        or canonical_digest(claim) != digest
        or claim.get("schema_version") != "fdai.genesis-entra-only-claim.v2"
        or claim.get("state") != "applying"
        or claim.get("source_commit") != context.source_commit
        or claim.get("environment") != context.environment
        or claim.get("target_profile_digest") != context.target_profile_digest
        or claim.get("control_profile_digest") != context.control_profile_digest
        or claim.get("snapshot_digest") != context.snapshot_digest
        or claim.get("run_binding") != context.run_binding
        or claim.get("target_binding") != context.target_binding
        or claim.get("executor_digest") != context.executor_digest
        or claim.get("execution_actor_digest") != context.executor_digest
        or claim.get("approval_principal_digest") == claim.get("execution_actor_digest")
        or claim.get("approval_executor_separated") is not True
        or claim.get("profile_digest") != observation.digest
        or claim.get("provider_admin_consent_granted") is not False
        or claim.get("mutation_performed") is not False
        or claim.get("subscription_ready") is not False
    ):
        raise ValueError("Entra-only claim context is invalid")
    claim["claim_digest"] = digest
    _validate_digests(
        claim,
        (
            "claim_digest",
            "target_profile_digest",
            "control_profile_digest",
            "snapshot_digest",
            "plan_digest",
            "profile_digest",
            "approval_actor_digest",
            "approval_principal_digest",
            "execution_actor_digest",
            "idempotency_key",
        ),
    )
    _validate_plan_projection(claim.get("plan"), str(claim["plan_digest"]))
    return claim


def load_receipt(path: Path, context: OperationContext) -> dict[str, object]:
    """Load one context-bound private receipt and verify its content digest."""

    receipt = _private_json(path, "Entra-only receipt")
    expected_fields = {
        "schema_version",
        "state",
        "source_commit",
        "environment",
        "target_profile_digest",
        "control_profile_digest",
        "snapshot_digest",
        "run_binding",
        "target_binding",
        "executor_digest",
        "plan_digest",
        "profile_digest",
        "approval_actor_digest",
        "approval_principal_digest",
        "execution_actor_digest",
        "approval_executor_separated",
        "plan",
        "readback_digest",
        "effects",
        "approval_verified",
        "claim_recorded",
        "readback_verified",
        "provider_admin_consent_granted",
        "foundation_invoked",
        "application_invoked",
        "recovered_from_claim",
        "mutation_performed",
        "subscription_ready",
        "receipt_digest",
    }
    digest = receipt.pop("receipt_digest", None)
    valid = (
        set(receipt) == expected_fields - {"receipt_digest"}
        and isinstance(digest, str)
        and canonical_digest(receipt) == digest
        and receipt.get("schema_version") == "fdai.genesis-entra-only-receipt.v2"
        and receipt.get("state") == "applied"
        and receipt.get("source_commit") == context.source_commit
        and receipt.get("environment") == context.environment
        and receipt.get("target_profile_digest") == context.target_profile_digest
        and receipt.get("control_profile_digest") == context.control_profile_digest
        and receipt.get("snapshot_digest") == context.snapshot_digest
        and receipt.get("run_binding") == context.run_binding
        and receipt.get("target_binding") == context.target_binding
        and receipt.get("executor_digest") == context.executor_digest
        and receipt.get("execution_actor_digest") == context.executor_digest
        and receipt.get("approval_principal_digest") != receipt.get("execution_actor_digest")
        and receipt.get("approval_executor_separated") is True
        and receipt.get("approval_verified") is True
        and receipt.get("claim_recorded") is True
        and receipt.get("readback_verified") is True
        and _effects_complete(receipt.get("effects"))
        and receipt.get("provider_admin_consent_granted") is False
        and receipt.get("foundation_invoked") is False
        and receipt.get("application_invoked") is False
        and isinstance(receipt.get("recovered_from_claim"), bool)
        and receipt.get("mutation_performed") is True
        and receipt.get("subscription_ready") is False
    )
    if not valid:
        raise ValueError("Entra-only receipt context is invalid")
    receipt["receipt_digest"] = digest
    _validate_digests(
        receipt,
        (
            "target_profile_digest",
            "control_profile_digest",
            "snapshot_digest",
            "plan_digest",
            "profile_digest",
            "approval_actor_digest",
            "approval_principal_digest",
            "execution_actor_digest",
            "readback_digest",
            "receipt_digest",
        ),
    )
    effects = receipt["effects"]
    if not isinstance(effects, dict):
        raise ValueError("Entra-only receipt effects are invalid")
    if effects["readback_digest"] != receipt["readback_digest"]:
        raise ValueError("Entra-only receipt effect digest is invalid")
    _validate_plan_projection(receipt.get("plan"), str(receipt["plan_digest"]))
    return receipt


def _validate_plan_projection(value: object, plan_digest: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "create_apps",
        "create_groups",
        "require_existing_role_groups",
        "role_group_binding_digest",
        "configure_api_roles_and_scope",
        "configure_runner_owned_spa_graph_permission",
        "provider_admin_consent",
        "plan_digest",
        "mutation_performed",
        "subscription_ready",
    }:
        raise ValueError("Entra-only retained plan is invalid")
    apps, groups = value.get("create_apps"), value.get("create_groups")
    if (
        value.get("schema_version") != "fdai.genesis-entra-plan.v1"
        or not isinstance(apps, list)
        or any(not isinstance(item, str) or item not in _APPS for item in apps)
        or apps != sorted(set(apps))
        or not isinstance(groups, list)
        or any(not isinstance(item, str) or item not in _GROUPS for item in groups)
        or groups != sorted(set(groups))
        or groups
        or value.get("require_existing_role_groups") is not True
        or not isinstance(value.get("role_group_binding_digest"), str)
        or _DIGEST.fullmatch(str(value["role_group_binding_digest"])) is None
        or value.get("configure_api_roles_and_scope") is not True
        or value.get("configure_runner_owned_spa_graph_permission") is not False
        or value.get("provider_admin_consent") is not False
        or value.get("plan_digest") != plan_digest
        or value.get("mutation_performed") is not False
        or value.get("subscription_ready") is not False
    ):
        raise ValueError("Entra-only retained plan is invalid")
    body = {
        key: item
        for key, item in value.items()
        if key not in {"plan_digest", "mutation_performed", "subscription_ready"}
    }
    if canonical_digest(body) != plan_digest:
        raise ValueError("Entra-only retained plan digest is invalid")


def _validate_digests(value: dict[str, object], fields: tuple[str, ...]) -> None:
    if any(
        not isinstance(value.get(name), str) or _DIGEST.fullmatch(str(value[name])) is None
        for name in fields
    ):
        raise ValueError("Entra-only record digest is invalid")


def _effects_complete(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value)
        == {
            "applications_verified",
            "service_principals_verified",
            "role_and_scope_definitions_verified",
            "group_role_assignments_verified",
            "owner_membership_changed_by_operation",
            "runner_spa_ownership_granted_by_operation",
            "graph_application_readwrite_ownedby_granted_by_operation",
            "provider_admin_consent_granted_by_operation",
            "readback_digest",
        }
        and all(
            value.get(key) is True
            for key in (
                "applications_verified",
                "service_principals_verified",
                "role_and_scope_definitions_verified",
                "group_role_assignments_verified",
            )
        )
        and all(
            value.get(key) is False
            for key in (
                "runner_spa_ownership_granted_by_operation",
                "graph_application_readwrite_ownedby_granted_by_operation",
                "provider_admin_consent_granted_by_operation",
                "owner_membership_changed_by_operation",
            )
        )
        and isinstance(value.get("readback_digest"), str)
        and _DIGEST.fullmatch(str(value["readback_digest"])) is not None
    )


def _private_json(path: Path, label: str) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=262_144),
        label=label,
        max_bytes=262_144,
    )
