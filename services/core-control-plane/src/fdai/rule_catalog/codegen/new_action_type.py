"""Pure-function codegen for a new :class:`OntologyActionType` YAML.

Renders the six required blocks (operation, interfaces,
rollback_contract, default_mode=shadow, promotion_gate,
preconditions/stop_conditions) with sensible defaults, then round-trips
through the action-type loader so a codegen bug fails-closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.\-]{0,79}\Z")

_ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "create",
        "update",
        "delete",
        "disable",
        "enable",
        "tag",
        "drop",
        "purge",
        "scale",
        "restart",
        "failover",
        "rotate",
        "revert",
        "attach",
        "detach",
        "quarantine",
    }
)

_ALLOWED_ROLLBACK: frozenset[str] = frozenset(
    {"pr_revert", "scripted", "pitr", "snapshot_restore", "state_forward_only"}
)

_ALLOWED_CATEGORIES: frozenset[str] = frozenset({"remediation", "ops", "governance"})

_ALLOWED_TRIGGERS: frozenset[str] = frozenset({"rule_violation", "operator_request", "both"})

_ALLOWED_INTERFACES: frozenset[str] = frozenset(
    {
        "ControlPlane",
        "DataPlaneMutating",
        "IdempotentByKey",
        "RateLimited",
        "RequiresInventoryFresh",
        "GraphTraversalRequired",
        "CrossResource",
        "AsymmetricRollback",
        "RequiresMaintenanceWindow",
    }
)

_ALLOWED_ROLES: frozenset[str] = frozenset({"reader", "contributor", "approver", "owner"})

_ALLOWED_TIER_CEILING: frozenset[str] = frozenset({"enforce_auto", "enforce_hil", "shadow_only"})


@dataclass(frozen=True, slots=True)
class PromotionGateSpec:
    min_shadow_days: int = 14
    min_samples: int = 30
    min_accuracy: float = 0.98
    max_policy_escapes: int = 0


@dataclass(frozen=True, slots=True)
class TierCeilingSpec:
    max_autonomy: str = "enforce_hil"
    min_role: str = "approver"


@dataclass(frozen=True, slots=True)
class ActionTypeSpec:
    name: str
    operation: str
    interfaces: tuple[str, ...]
    rollback_contract: str
    category: str
    description: str
    default_mode: str = "shadow"
    irreversible: bool = False
    promotion_gate: PromotionGateSpec = field(default_factory=PromotionGateSpec)
    trigger_kind: str = "rule_violation"
    execution_path: str = "pr_native"
    ceiling_t0: TierCeilingSpec = field(default_factory=TierCeilingSpec)
    ceiling_t1: TierCeilingSpec = field(
        default_factory=lambda: TierCeilingSpec(max_autonomy="shadow_only", min_role="approver")
    )
    ceiling_t2: TierCeilingSpec = field(
        default_factory=lambda: TierCeilingSpec(max_autonomy="shadow_only", min_role="approver")
    )
    prod_downgrade_mode: str = "enforce_hil"
    argument_schema: dict[str, Any] | None = None
    version: str = "1.0.0"
    schema_version: str = "1.0.0"
    header_comment: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _NAME_PATTERN.match(self.name):
            raise ValueError(f"ActionType name {self.name!r} MUST match {_NAME_PATTERN.pattern}")
        if self.operation not in _ALLOWED_OPERATIONS:
            raise ValueError(f"operation {self.operation!r} not in {sorted(_ALLOWED_OPERATIONS)!r}")
        if self.rollback_contract not in _ALLOWED_ROLLBACK:
            raise ValueError(
                f"rollback_contract {self.rollback_contract!r} not in {sorted(_ALLOWED_ROLLBACK)!r}"
            )
        if self.category not in _ALLOWED_CATEGORIES:
            raise ValueError(f"category {self.category!r} not in {sorted(_ALLOWED_CATEGORIES)!r}")
        if self.trigger_kind not in _ALLOWED_TRIGGERS:
            raise ValueError(
                f"trigger_kind {self.trigger_kind!r} not in {sorted(_ALLOWED_TRIGGERS)!r}"
            )
        if self.default_mode not in ("shadow", "enforce"):
            raise ValueError(f"default_mode {self.default_mode!r} MUST be shadow|enforce")
        if self.default_mode == "enforce":
            raise ValueError(
                "default_mode='enforce' is forbidden for a scaffolded ActionType; "
                "ship in shadow and promote via a separate PR"
            )
        if self.prod_downgrade_mode not in ("enforce_hil", "shadow_only"):
            raise ValueError(
                f"prod_downgrade_mode {self.prod_downgrade_mode!r} MUST be enforce_hil|shadow_only"
            )
        for iface in self.interfaces:
            if iface not in _ALLOWED_INTERFACES:
                raise ValueError(f"interface {iface!r} not in {sorted(_ALLOWED_INTERFACES)!r}")
        if not self.interfaces:
            raise ValueError("ActionType MUST declare at least one interface")
        for ceiling in (self.ceiling_t0, self.ceiling_t1, self.ceiling_t2):
            if ceiling.max_autonomy not in _ALLOWED_TIER_CEILING:
                raise ValueError(
                    f"max_autonomy {ceiling.max_autonomy!r} not in "
                    f"{sorted(_ALLOWED_TIER_CEILING)!r}"
                )
            if ceiling.min_role not in _ALLOWED_ROLES:
                raise ValueError(f"min_role {ceiling.min_role!r} not in {sorted(_ALLOWED_ROLES)!r}")
        if self.trigger_kind in ("operator_request", "both") and not self.argument_schema:
            raise ValueError("trigger_kind 'operator_request' / 'both' MUST supply argument_schema")


def render_action_type_yaml(spec: ActionTypeSpec) -> str:
    """Return fully-rendered YAML text for ``spec`` (validated through the loader)."""
    doc: dict[str, Any] = {
        "schema_version": spec.schema_version,
        "name": spec.name,
        "version": spec.version,
        "operation": spec.operation,
        "interfaces": list(spec.interfaces),
        "rollback_contract": spec.rollback_contract,
        "irreversible": spec.irreversible,
        "default_mode": spec.default_mode,
        "promotion_gate": {
            "min_shadow_days": spec.promotion_gate.min_shadow_days,
            "min_samples": spec.promotion_gate.min_samples,
            "min_accuracy": spec.promotion_gate.min_accuracy,
            "max_policy_escapes": spec.promotion_gate.max_policy_escapes,
        },
        "preconditions": [{"kind": "no_conflicting_open_action_on_resource"}],
        "stop_conditions": [
            {"kind": "provider_api_error_streak", "count": 3},
            {"kind": "time_box_exceeded_seconds", "seconds": 300},
        ],
        "blast_radius": {
            "computation": "static_enum",
            "static_bucket": "resource",
        },
        "description": spec.description,
        "category": spec.category,
        "trigger_kind": {"kind": spec.trigger_kind},
        "execution_path": spec.execution_path,
        "ceiling_by_tier": {
            "t0": {
                "max_autonomy": spec.ceiling_t0.max_autonomy,
                "min_role": spec.ceiling_t0.min_role,
            },
            "t1": {
                "max_autonomy": spec.ceiling_t1.max_autonomy,
                "min_role": spec.ceiling_t1.min_role,
            },
            "t2": {
                "max_autonomy": spec.ceiling_t2.max_autonomy,
                "min_role": spec.ceiling_t2.min_role,
            },
        },
        "prod_downgrade": {
            "mode": spec.prod_downgrade_mode,
            "detection_ref": "risk-classification/env-detector",
        },
    }
    if spec.argument_schema is not None:
        doc["argument_schema"] = spec.argument_schema

    load_action_type_from_mapping(doc, schema_registry=PackageResourceSchemaRegistry())

    header = _render_header(spec)
    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    return f"{header}{body}"


def _render_header(spec: ActionTypeSpec) -> str:
    if not spec.header_comment:
        return ""
    return "\n".join(f"# {line}" for line in spec.header_comment) + "\n"


__all__ = [
    "ActionTypeSpec",
    "PromotionGateSpec",
    "TierCeilingSpec",
    "render_action_type_yaml",
]
