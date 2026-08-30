"""Sealed intent and sanitized observations for Azure bootstrap reconciliation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest

FOUNDATION_PROVIDER_NAMESPACES = (
    "Microsoft.Authorization",
    "Microsoft.Compute",
    "Microsoft.DevTestLab",
    "Microsoft.EventGrid",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.Resources",
    "Microsoft.Storage",
)

_RESOURCE_GROUP_NAME = re.compile(r"^[A-Za-z0-9._()\-]{1,90}$")
_STORAGE_ACCOUNT_NAME = re.compile(r"^[a-z0-9]{3,24}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class Classification(StrEnum):
    """Disposition of one read-only bootstrap observation."""

    COMPATIBLE = "compatible"
    MISSING = "missing"
    CONFLICT = "conflict"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class BootstrapObservation:
    """Sanitized classification that contains no Azure resource identifiers."""

    entry_id: str
    classification: Classification
    reason_code: str

    def to_mapping(self) -> dict[str, str]:
        """Return canonical observation data."""

        return {
            "entry_id": self.entry_id,
            "classification": self.classification.value,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class BootstrapReconcileResult:
    """Sealed bootstrap intent plus separate time-bound observations."""

    intent: Mapping[str, object]
    observations: tuple[BootstrapObservation, ...]
    created_at: str
    expires_at: str

    @property
    def plan_digest(self) -> str:
        """Return the replay-stable digest of bootstrap intent only."""

        return canonical_digest(self.intent)

    @property
    def observation_digest(self) -> str:
        """Return the digest of the time-bound observed state."""

        return canonical_digest(
            {
                "created_at": self.created_at,
                "expires_at": self.expires_at,
                "observations": [item.to_mapping() for item in self.observations],
            }
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        """Return conflicts and unknown state that block approval."""

        return tuple(
            item.reason_code
            for item in self.observations
            if item.classification in {Classification.CONFLICT, Classification.INDETERMINATE}
        )

    def to_mapping(self) -> dict[str, object]:
        """Return a private artifact without raw tenant or subscription identifiers."""

        return {
            "schema_version": "fdai.bootstrap-reconcile-plan.v1",
            "state": "review" if not self.blockers else "incomplete",
            "plan": dict(self.intent),
            "plan_digest": self.plan_digest,
            "observation": {
                "created_at": self.created_at,
                "expires_at": self.expires_at,
                "digest": self.observation_digest,
                "entries": [item.to_mapping() for item in self.observations],
            },
            "reason_codes": list(self.blockers),
            "mutation_performed": False,
        }


def build_intent(
    *,
    profile: ProvisionProfile,
    source_commit: str,
    ops_resource_group: str,
    app_resource_group: str,
    state_storage_account: str,
) -> dict[str, object]:
    """Build deterministic foundation intent without live observations."""

    operations = [
        {
            "entry_id": f"provider.{namespace.casefold()}",
            "action": "ensure_registered",
            "postcondition": "provider.registered",
            "rollback_ref": "rollback.provider-registration",
        }
        for namespace in FOUNDATION_PROVIDER_NAMESPACES
    ]
    operations.extend(
        (
            {
                "entry_id": "ops-resource-group",
                "action": "ensure",
                "postcondition": "resource-group.compatible",
                "rollback_ref": "rollback.ops-resource-group",
            },
            {
                "entry_id": "application-resource-group",
                "action": "ensure",
                "postcondition": "resource-group.compatible",
                "rollback_ref": "rollback.application-resource-group",
            },
            {
                "entry_id": "state-storage",
                "action": "ensure",
                "postcondition": "state-storage.private-keyless-versioned",
                "rollback_ref": "rollback.state-storage",
            },
            {
                "entry_id": "ops-network",
                "action": "ensure",
                "postcondition": "ops-network.private-runner-ready",
                "rollback_ref": "rollback.ops-network",
            },
            {
                "entry_id": "deploy-identity",
                "action": "ensure",
                "postcondition": "deploy-identity.roles-effective",
                "rollback_ref": "rollback.deploy-identity",
            },
            {
                "entry_id": "runner",
                "action": "ensure",
                "postcondition": "runner.attested",
                "rollback_ref": "rollback.runner",
            },
            {
                "entry_id": "state-containers",
                "action": "ensure",
                "postcondition": "state-containers.private",
                "rollback_ref": "rollback.state-containers",
            },
            {
                "entry_id": "state-handoff",
                "action": "verify",
                "postcondition": "state-handoff.zero-change",
                "rollback_ref": "rollback.state-handoff",
            },
        )
    )
    return {
        "schema_version": "fdai.bootstrap-reconcile-intent.v1",
        "source_commit": source_commit,
        "profile_digest": canonical_digest(profile.to_mapping()),
        "target_binding": profile.target_binding,
        "environment": profile.environment,
        "region": profile.region,
        "resource_names": {
            "ops_resource_group": ops_resource_group,
            "application_resource_group": app_resource_group,
            "state_storage_account": state_storage_account,
        },
        "state_storage_posture": {
            "kind": "StorageV2",
            "sku": "Standard_LRS",
            "minimum_tls_version": "TLS1_2",
            "public_network_access": "Disabled",
            "shared_key_access": False,
            "blob_public_access": False,
            "cross_tenant_replication": False,
            "blob_versioning": True,
            "blob_delete_retention": True,
            "container_delete_retention": True,
            "containers": ["tfstate", "deployment-plans"],
        },
        "provider_namespaces": list(FOUNDATION_PROVIDER_NAMESPACES),
        "operations": operations,
    }


def validate_inputs(
    *,
    source_commit: str,
    ops_resource_group: str,
    app_resource_group: str,
    state_storage_account: str,
    ttl_seconds: int,
) -> None:
    """Reject names and bounds that Azure cannot safely apply later."""

    if _SHA.fullmatch(source_commit) is None:
        raise ValueError("source_commit MUST be a lowercase 40-character SHA")
    for value in (ops_resource_group, app_resource_group):
        if _RESOURCE_GROUP_NAME.fullmatch(value) is None or value.endswith("."):
            raise ValueError("Azure resource group name is invalid")
    if _STORAGE_ACCOUNT_NAME.fullmatch(state_storage_account) is None:
        raise ValueError("Azure storage account name is invalid")
    if not 60 <= ttl_seconds <= 3600:
        raise ValueError("bootstrap plan ttl MUST be from 60 through 3600 seconds")


def timestamp(moment: datetime) -> str:
    """Render one canonical UTC timestamp."""

    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
