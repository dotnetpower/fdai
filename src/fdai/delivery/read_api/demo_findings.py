"""Demo findings provider - real Rego evaluation over synthetic inventory.

Backs ``GET /rules/{id}/findings`` in the local dev harness so the
console's "Affected resources" section shows *real* results: each
synthetic resource below is evaluated by the shipped OPA policy for the
selected rule, and a finding is emitted only when the real Rego ``deny``
fires - the ``problem`` text is the policy's own ``deny_reason``, never
fabricated.

The inventory is entirely synthetic and customer-agnostic (placeholder
subscription id, ``demo-*`` names). This module is wired only by
:mod:`fdai.delivery.read_api._local` (dev), never by a production
composition root - the same pattern as
:class:`~fdai.delivery.read_api.live_stream.SyntheticLiveEmitter`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fdai.core.tiers.t0_deterministic.opa_evaluator import OpaRegoEvaluator
from fdai.delivery.read_api.rule_catalog import FindingsProvider
from fdai.shared.contracts.models import Rule

# Fixed observation time keeps the demo deterministic (no wall-clock).
_DEMO_OBSERVED_AT = "2026-07-09T00:00:00Z"

# Synthetic subscription id - the all-zero placeholder the repo mandates
# for GUID-shaped ids (see generic-scope.instructions.md).
_SUB = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class SyntheticResource:
    """One demo resource: an id, a display name, a type, and its props.

    ``props`` mirror the ``input.resource.props`` shape the Rego policies
    read. Fields are chosen so a handful of shipped rules deny with a
    real reason; unmatched rules simply abstain (no finding).
    """

    resource_id: str
    resource_name: str
    resource_type: str
    props: Mapping[str, Any] = field(default_factory=dict)


def _rid(kind: str, name: str) -> str:
    return f"/subscriptions/{_SUB}/resourceGroups/rg-demo/providers/{kind}/{name}"


# Each resource is crafted to violate several shipped policies at once so
# clicking a rule surfaces a concrete, really-evaluated example.
SYNTHETIC_INVENTORY: tuple[SyntheticResource, ...] = (
    SyntheticResource(
        resource_id=_rid("Microsoft.Compute/disks", "demo-disk-orphan"),
        resource_name="demo-disk-orphan",
        resource_type="disk",
        props={"managed_by": "", "snapshot_policy_id": ""},
    ),
    SyntheticResource(
        resource_id=_rid("Microsoft.Storage/storageAccounts", "demostgpublic"),
        resource_name="demostgpublic",
        resource_type="object-storage",
        props={
            "public_access": "enabled",
            "enable_https_traffic_only": False,
            "min_tls_version": "TLS1_0",
            "allow_shared_key_access": True,
            "blob_versioning_enabled": False,
            "blob_soft_delete_enabled": False,
            "infrastructure_encryption_enabled": False,
            "public_network_access_enabled": True,
            "private_endpoints": [],
            "diagnostic_settings": [],
            "tags": {},
        },
    ),
    SyntheticResource(
        resource_id=_rid("Microsoft.DBforPostgreSQL/flexibleServers", "demo-pg-single"),
        resource_name="demo-pg-single",
        resource_type="postgresql-server",
        props={
            "ha_mode": "Disabled",
            "ssl_enforcement_enabled": False,
            "geo_redundant_backup_enabled": False,
            "diagnostic_settings": [],
        },
    ),
    SyntheticResource(
        resource_id=_rid("Microsoft.KeyVault/vaults", "demo-kv-open"),
        resource_name="demo-kv-open",
        resource_type="secret-store",
        props={
            "purge_protection_enabled": False,
            "public_network_access_enabled": True,
            "rbac_authorization_enabled": False,
            "soft_delete_enabled": False,
            "age_days": 999,
            "diagnostic_settings": [],
        },
    ),
    SyntheticResource(
        resource_id=_rid("Microsoft.Sql/servers/databases", "demo-sql-01"),
        resource_name="demo-sql-01",
        resource_type="sql-database",
        props={
            "geo_redundant_backup_enabled": False,
            "audit_enabled": False,
            "zone_redundant": False,
            "tde_enabled": False,
            "diagnostic_settings": [],
        },
    ),
    SyntheticResource(
        resource_id=_rid("Microsoft.ManagedIdentity/userAssignedIdentities", "demo-mi-priv"),
        resource_name="demo-mi-priv",
        resource_type="managed-identity",
        props={
            "role_assignments": [{"scope": "subscription", "role_name": "Owner"}],
        },
    ),
)


def _humanize_reason(deny_reason: str | None) -> str:
    if not deny_reason:
        return "Violates this rule (see the check logic for the exact condition)."
    return deny_reason.replace("_", " ").strip().capitalize()


def build_demo_findings_provider(
    *,
    rules_by_id: Mapping[str, Rule],
    policies_root: Path,
    evaluator: Any = None,
    inventory: Sequence[SyntheticResource] = SYNTHETIC_INVENTORY,
) -> FindingsProvider:
    """Return a :data:`FindingsProvider` backed by real Rego evaluation.

    ``evaluator`` defaults to an :class:`OpaRegoEvaluator` (requires the
    ``opa`` binary; the caller guards ``MissingOpaBinaryError``). It is
    injectable so tests can supply a deterministic stub without OPA.
    """

    resolved_evaluator = evaluator or OpaRegoEvaluator(policies_root=policies_root)

    def _evaluate(rule: Rule) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for res in inventory:
            if res.resource_type != rule.resource_type:
                continue
            try:
                result = resolved_evaluator.evaluate(rule, res.props)
            except Exception:  # noqa: BLE001 - one bad eval must not fail the view
                logging.getLogger(__name__).debug(
                    "demo_finding_eval_failed rule=%s resource=%s",
                    rule.id,
                    res.resource_id,
                    exc_info=True,
                )
                continue
            if result is None or not result.denied:
                continue
            deny_reason = result.context.get("deny_reason")
            out.append(
                {
                    "resource_id": res.resource_id,
                    "resource_name": res.resource_name,
                    "severity": rule.severity.value,
                    "problem": _humanize_reason(deny_reason),
                    "context": dict(result.context),
                    "observed_at": _DEMO_OBSERVED_AT,
                }
            )
        return out

    async def provider(rule_id: str, origin: str) -> Sequence[Mapping[str, Any]]:
        del origin  # demo inventory is origin-agnostic
        rule = rules_by_id.get(rule_id)
        if rule is None:
            return []
        # OPA eval shells out; run off the event loop so it never blocks.
        return await asyncio.to_thread(_evaluate, rule)

    return provider


__all__ = [
    "SYNTHETIC_INVENTORY",
    "SyntheticResource",
    "build_demo_findings_provider",
]
