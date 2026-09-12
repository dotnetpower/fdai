"""Discover Cost Governance review targets from exact shipped catalogs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .resource_loader import load_resource_bytes, load_resource_manifest
from .validation import CostReadinessTargetKind, CostReadinessThresholds


@dataclass(frozen=True, slots=True)
class CostReadinessTarget:
    """One independently reviewed target and its catalog-owned gate."""

    kind: CostReadinessTargetKind
    target_id: str
    thresholds: CostReadinessThresholds


def load_cost_readiness_targets(catalog_root: Path) -> tuple[CostReadinessTarget, ...]:
    """Load the complete package target set without deriving promotion authority."""

    manifest = load_resource_manifest()
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Cost Governance resource manifest assets are invalid")
    action_ids = sorted(
        {
            reference.removeprefix("action:")
            for asset in assets
            if isinstance(asset, dict)
            for reference in _references(asset)
            if reference.startswith("action:")
        }
    )
    workflows = sorted(
        (
            str(asset["id"]).removeprefix("workflow:"),
            str(asset["path"]),
        )
        for asset in assets
        if isinstance(asset, dict) and asset.get("kind") == "workflow"
    )
    if not action_ids or not workflows:
        raise ValueError("Cost Governance review targets MUST include actions and workflows")

    action_targets = tuple(
        CostReadinessTarget(
            kind=CostReadinessTargetKind.ACTION_TYPE,
            target_id=action_id,
            thresholds=_thresholds(
                _yaml_object(
                    (catalog_root / "action-types" / f"{action_id}.yaml").read_bytes(),
                    label=f"ActionType {action_id}",
                )
            ),
        )
        for action_id in action_ids
    )
    workflow_targets = tuple(
        CostReadinessTarget(
            kind=CostReadinessTargetKind.WORKFLOW,
            target_id=workflow_id,
            thresholds=_thresholds(
                _yaml_object(
                    load_resource_bytes(path),
                    label=f"Workflow {workflow_id}",
                )
            ),
        )
        for workflow_id, path in workflows
    )
    governed_targets = (*action_targets, *workflow_targets)
    package_thresholds = CostReadinessThresholds(
        minimum_samples=max(item.thresholds.minimum_samples for item in governed_targets),
        minimum_shadow_dwell_seconds=max(
            item.thresholds.minimum_shadow_dwell_seconds for item in governed_targets
        ),
        minimum_accuracy=max(item.thresholds.minimum_accuracy for item in governed_targets),
    )
    return (
        CostReadinessTarget(
            kind=CostReadinessTargetKind.PACKAGE_ACTIVATION,
            target_id="cost-governance",
            thresholds=package_thresholds,
        ),
        *action_targets,
        *workflow_targets,
    )


def _references(asset: dict[str, object]) -> tuple[str, ...]:
    raw = asset.get("references")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("Cost Governance resource references are invalid")
    return tuple(raw)


def _thresholds(document: dict[str, Any]) -> CostReadinessThresholds:
    gate = document.get("promotion_gate")
    if not isinstance(gate, dict) or gate.get("max_policy_escapes") != 0:
        raise ValueError("Cost Governance promotion gate MUST require zero policy escapes")
    try:
        days = int(gate["min_shadow_days"])
        samples = int(gate["min_samples"])
        accuracy = Decimal(str(gate["min_accuracy"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Cost Governance promotion gate is invalid") from exc
    return CostReadinessThresholds(
        minimum_samples=samples,
        minimum_shadow_dwell_seconds=days * 86_400,
        minimum_accuracy=accuracy,
    )


def _yaml_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} is invalid YAML") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST contain an object")
    return value


__all__ = ["CostReadinessTarget", "load_cost_readiness_targets"]
