"""Exact-file JSON IaC patching beneath governed manual-PR execution."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan

from fdai.delivery.alert_noise_metric_iac import patch_metric_evaluation


@dataclass(frozen=True, slots=True)
class AlertIaCBinding:
    """Private deployment-owned file and object selector, not operator-supplied content."""

    path: str
    source_digest: str
    resource_type: str
    resource_name: str
    field: str
    group_ids: Mapping[str, str]
    target_ref: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or any(part in {"..", ".git"} for part in path.parts)
            or str(path) != self.path
            or re.fullmatch(r"[A-Za-z0-9_./-]+\.tf\.json", self.path) is None
            or len(self.path) > 512
        ):
            raise ValueError("alert IaC path MUST name a relative existing Terraform JSON file")
        if (
            re.fullmatch(r"sha256:[a-f0-9]{64}", self.source_digest) is None
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,127}", self.resource_name) is None
            or re.fullmatch(r"[a-z][a-z0-9_.:-]{0,159}", self.target_ref) is None
            or len(self.group_ids) > 1000
            or any(
                type(key) is not str or type(value) is not str
                for key, value in self.group_ids.items()
            )
        ):
            raise ValueError("alert IaC binding is malformed")
        object.__setattr__(self, "group_ids", MappingProxyType(dict(self.group_ids)))
        if self.resource_type not in {
            "azurerm_monitor_metric_alert",
            "azurerm_monitor_scheduled_query_rules_alert_v2",
            "azurerm_monitor_alert_processing_rule_suppression",
        }:
            raise ValueError("alert IaC resource type is not supported")


@dataclass(frozen=True, slots=True)
class AlertIaCPatch:
    """A source-bound forward/restore pair; no file or provider writes occur here."""

    path: str
    source_digest: str
    result_digest: str
    forward: str
    rollback: str


def render_alert_iac(
    plan: AlertChangePlan,
    evidence: AlertEvidence,
    *,
    binding: AlertIaCBinding,
    source: str,
) -> AlertIaCPatch:
    """Change one declared field in an existing resource, preserving all unrelated JSON."""
    plan, evidence = AlertChangePlan.model_validate(plan), AlertEvidence.model_validate(evidence)
    if len(source.encode()) > 1_000_000 or _hash(source) != binding.source_digest:
        raise ValueError("alert IaC source revision mismatch")
    if digest_record(evidence) != plan.evidence_digest:
        raise ValueError("alert IaC evidence mismatch")
    if binding.target_ref != (plan.treatment.processing_rule_ref or plan.treatment.target_ref):
        raise ValueError("alert IaC target differs from the reviewed plan")
    document = json.loads(source, object_pairs_hook=_unique)
    if not isinstance(document, dict):
        raise ValueError("alert IaC document MUST be an object")
    changed = copy.deepcopy(document)
    try:
        resource = changed["resource"][binding.resource_type][binding.resource_name]
    except (KeyError, TypeError):
        raise ValueError("alert IaC existing resource is unavailable") from None
    if not isinstance(resource, dict):
        raise ValueError("alert IaC resource is malformed")
    treatment = plan.treatment
    if treatment.kind == "routing":
        if (
            binding.field != "action"
            or not isinstance(resource.get("action"), list)
            or binding.resource_type == "azurerm_monitor_alert_processing_rule_suppression"
        ):
            raise ValueError("alert routing requires the exact existing action list")
        old = binding.group_ids.get(treatment.remove_group_ref or "")
        new = binding.group_ids.get(treatment.replacement_group_ref or "")
        if not old or not new or old == new:
            raise ValueError("alert IaC group mapping is incomplete")
        actions = resource["action"]
        if binding.resource_type == "azurerm_monitor_metric_alert":
            if any(
                not isinstance(item, dict) or type(item.get("action_group_id")) is not str
                for item in actions
            ):
                raise ValueError("alert IaC metric action shape is invalid")
            matched = [item for item in actions if item["action_group_id"] == old]
            if len(matched) != 1 or any(item["action_group_id"] == new for item in actions):
                raise ValueError("alert IaC source or replacement group is ambiguous")
            matched[0]["action_group_id"] = new
        else:
            if (
                len(actions) != 1
                or not isinstance(actions[0], dict)
                or not isinstance(actions[0].get("action_groups"), list)
            ):
                raise ValueError("alert IaC scheduled query action shape is invalid")
            groups = actions[0]["action_groups"]
            if (
                groups.count(old) != 1
                or new in groups
                or any(type(item) is not str for item in groups)
            ):
                raise ValueError("alert IaC source or replacement group is ambiguous")
            groups[groups.index(old)] = new
    elif treatment.kind == "evaluation":
        rule = next(rule for rule in evidence.rules if rule.ref == treatment.target_ref)
        if (
            rule.evaluation is None
            or treatment.evaluation is None
            or binding.resource_type != "azurerm_monitor_metric_alert"
        ):
            raise ValueError("alert IaC evaluation mapping is unsupported")
        patch_metric_evaluation(
            resource, rule.evaluation, treatment.evaluation, field=binding.field
        )
    else:
        if (
            binding.resource_type != "azurerm_monitor_alert_processing_rule_suppression"
            or binding.field != "schedule"
        ):
            raise ValueError("alert IaC suppression target mismatch")
        if (
            resource.get("enabled") is not False
            or treatment.starts_at is None
            or treatment.ends_at is None
        ):
            raise ValueError("alert IaC suppression MUST start from an inert existing rule")
        resource["enabled"] = True
        resource["schedule"] = [
            {
                "effective_from": treatment.starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                "effective_until": treatment.ends_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                "time_zone": "UTC",
            }
        ]
    forward = json.dumps(changed, sort_keys=True, indent=2, allow_nan=False) + "\n"
    return AlertIaCPatch(binding.path, binding.source_digest, _hash(forward), forward, source)


def conditional_restore(patch: AlertIaCPatch, *, current: str) -> str:
    """Restore only the exact applied revision; never overwrite a later concurrent edit."""
    if _hash(current) != patch.result_digest:
        raise ValueError("alert rollback conflicts with a newer IaC revision")
    return patch.rollback


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate IaC field")
        result[key] = value
    return result
