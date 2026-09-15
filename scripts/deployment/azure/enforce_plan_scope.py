#!/usr/bin/env python3
"""Enforce bounded Terraform plan scopes for specialized deploy modes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_deploy_identity_plan import validate_plan as validate_deploy_identity_plan  # noqa: E402

_DESIGN_MOCKS = frozenset({"module.design_mocks[0].azurerm_static_web_app.design_mocks"})
_PRIMARY_REASONER = (
    'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t2.reasoner.primary"]'
)
_CORE_MODEL_QUORUM = frozenset(
    {
        "module.llm_azure_openai[0].azurerm_cognitive_account.primary",
        'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["t1.judge"]',
        (
            "module.llm_azure_openai[0].azurerm_cognitive_deployment."
            'capability["t2.reasoner.primary"]'
        ),
    }
)
_RCA_READER_IDENTITY = frozenset(
    {
        "module.rca_reader_identity.azurerm_user_assigned_identity.primary",
        "azurerm_role_assignment.rca_monitoring_reader",
    }
)
_OBSERVABILITY_ANALYZER = frozenset({"terraform_data.observability_analyzer_image_update"})
_PROVIDER_SCHEMA = frozenset({"azurerm_container_app_job.provider_schema[0]"})
_RUNTIME_CALL_EVIDENCE = frozenset(
    {
        "terraform_data.inventory_runtime_image_update",
        "terraform_data.runtime_call_evidence_transition",
        "terraform_data.runtime_workspace_binding_transition",
    }
)
_COST_GOVERNANCE = frozenset(
    {
        "azurerm_role_assignment.inventory_cost_reader",
        "azurerm_container_app_job.cost_governance_analyzer[0]",
        "azurerm_container_app_job.cost_governance_collector[0]",
    }
)
_ALERT_NOISE_PILOT_ACTION_GROUP = "module.alert_noise_pilot[0].azurerm_monitor_action_group.pilot"
_ALERT_NOISE_PILOT_RULE = "module.alert_noise_pilot[0].azurerm_monitor_metric_alert.pilot"
_ALERT_NOISE_PILOT = frozenset({_ALERT_NOISE_PILOT_ACTION_GROUP, _ALERT_NOISE_PILOT_RULE})
_ALERT_NOISE_BASELINE_THRESHOLD = 0.0
_ALERT_NOISE_TREATMENT_THRESHOLD = 101.0
_ALERT_NOISE_RECEIVER_COLLECTIONS = (
    "arm_role_receiver",
    "automation_runbook_receiver",
    "azure_app_push_receiver",
    "azure_function_receiver",
    "event_hub_receiver",
    "itsm_receiver",
    "logic_app_receiver",
    "sms_receiver",
    "voice_receiver",
    "webhook_receiver",
)
_OPERATIONAL_HISTORY_PREFIXES = (
    "module.operational_history_storage[0].",
    "azurerm_private_endpoint.operational_history_blob[0]",
    "azurerm_private_dns_a_record.operational_history_runner_blob[0]",
    "module.decision_evidence_storage[0].",
    "azurerm_private_endpoint.decision_evidence_blob[0]",
    "azurerm_private_dns_a_record.decision_evidence_runner_blob[0]",
    "azurerm_role_assignment.decision_evidence_inventory_reader[0]",
    "azurerm_container_app_job.operational_history_lifecycle[0]",
    "module.resource_group.terraform_data.ownership",
)


def changed_addresses(plan: dict[str, Any]) -> frozenset[str]:
    """Return addresses whose actions are neither reads nor no-ops."""
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise ValueError("Terraform plan resource_changes must be an array")
    return frozenset(
        str(change.get("address", "unknown"))
        for change in changes
        if isinstance(change, dict)
        and change.get("change", {}).get("actions", []) not in (["no-op"], ["read"])
    )


def _model_addresses(resolved: dict[str, Any]) -> frozenset[str]:
    capabilities = resolved.get("capabilities")
    if not isinstance(capabilities, list):
        raise ValueError("resolved model capabilities must be an array")
    allowed: set[str] = set()
    for item in capabilities:
        if not isinstance(item, dict):
            raise ValueError("resolved model capability must be an object")
        if item.get("status") == "hil-only":
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("resolved model capability name is required")
        allowed.add(f'module.llm_azure_openai[0].azurerm_cognitive_deployment.capability["{name}"]')
    return frozenset(allowed)


def _canonical_digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def _pilot_threshold(resource: dict[str, Any] | None) -> float | None:
    if not isinstance(resource, dict):
        return None
    criteria = resource.get("criteria")
    if not isinstance(criteria, list) or len(criteria) != 1 or not isinstance(criteria[0], dict):
        return None
    threshold = criteria[0].get("threshold")
    return float(threshold) if isinstance(threshold, (int, float)) else None


def _without_pilot_threshold(resource: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(resource))
    criteria = value.get("criteria")
    if not isinstance(criteria, list) or len(criteria) != 1 or not isinstance(criteria[0], dict):
        raise ValueError("Alert-noise pilot rule must have exactly one metric criterion")
    criteria[0].pop("threshold", None)
    return value


def _pilot_group_is_safe(resource: dict[str, Any] | None) -> bool:
    if not isinstance(resource, dict):
        return False
    email = resource.get("email_receiver")
    if (
        not isinstance(email, list)
        or len(email) != 1
        or not isinstance(email[0], dict)
        or email[0].get("name") != "approved-test-recipient"
        or not isinstance(email[0].get("email_address"), str)
        or not email[0].get("email_address", "").strip()
        or email[0].get("use_common_alert_schema") is not True
    ):
        return False
    return all(resource.get(name) in (None, []) for name in _ALERT_NOISE_RECEIVER_COLLECTIONS)


def _pilot_rule_is_safe(
    resource: dict[str, Any] | None, *, allowed_thresholds: frozenset[float]
) -> bool:
    if not isinstance(resource, dict):
        return False
    criteria = resource.get("criteria")
    actions = resource.get("action")
    scopes = resource.get("scopes")
    if (
        not isinstance(criteria, list)
        or len(criteria) != 1
        or not isinstance(criteria[0], dict)
        or criteria[0].get("metric_namespace") != "Microsoft.KeyVault/vaults"
        or criteria[0].get("metric_name") != "Availability"
        or criteria[0].get("aggregation") != "Average"
        or criteria[0].get("operator") != "LessThan"
        or _pilot_threshold(resource) not in allowed_thresholds
        or resource.get("severity") != 3
        or resource.get("auto_mitigate") is not True
        or resource.get("enabled") is not True
        or resource.get("frequency") != "PT5M"
        or resource.get("window_size") != "PT5M"
        or not isinstance(actions, list)
        or len(actions) != 1
        or not isinstance(scopes, list)
        or len(scopes) != 1
        or not isinstance(scopes[0], str)
        or re.fullmatch(
            r"(?i)/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/"
            r"Microsoft\.KeyVault/vaults/[^/]+",
            scopes[0],
        )
        is None
    ):
        return False
    return True


def _validate_alert_noise_pilot(plan: dict[str, Any], changed: frozenset[str]) -> None:
    unexpected = sorted(changed.difference(_ALERT_NOISE_PILOT))
    if unexpected:
        raise ValueError(
            "Alert-noise pilot plan contains changes outside its bounded scope: "
            + ", ".join(unexpected)
        )
    changes = {
        str(item.get("address")): item.get("change", {})
        for item in plan.get("resource_changes", [])
        if isinstance(item, dict) and str(item.get("address")) in changed
    }
    if not changes:
        return
    if changed == _ALERT_NOISE_PILOT:
        actions = {address: change.get("actions") for address, change in changes.items()}
        if all(value == ["create"] for value in actions.values()):
            rule = changes[_ALERT_NOISE_PILOT_RULE].get("after")
            group = changes[_ALERT_NOISE_PILOT_ACTION_GROUP].get("after")
            if not _pilot_group_is_safe(group) or not _pilot_rule_is_safe(
                rule,
                allowed_thresholds=frozenset({_ALERT_NOISE_BASELINE_THRESHOLD}),
            ):
                raise ValueError("Alert-noise pilot create plan violates the inert baseline")
            return
        if all(value == ["delete"] for value in actions.values()):
            rule = changes[_ALERT_NOISE_PILOT_RULE].get("before")
            group = changes[_ALERT_NOISE_PILOT_ACTION_GROUP].get("before")
            if not _pilot_group_is_safe(group) or not _pilot_rule_is_safe(
                rule,
                allowed_thresholds=frozenset(
                    {_ALERT_NOISE_BASELINE_THRESHOLD, _ALERT_NOISE_TREATMENT_THRESHOLD}
                ),
            ):
                raise ValueError("Alert-noise pilot cleanup cannot delete a drifted resource pair")
            return
        raise ValueError(
            "Alert-noise pilot pair must be a create-only baseline or delete-only cleanup"
        )
    if changed == frozenset({_ALERT_NOISE_PILOT_RULE}):
        change = changes[_ALERT_NOISE_PILOT_RULE]
        before = change.get("before")
        after = change.get("after")
        if (
            change.get("actions") != ["update"]
            or not isinstance(before, dict)
            or not isinstance(after, dict)
            or not _pilot_rule_is_safe(
                before,
                allowed_thresholds=frozenset(
                    {_ALERT_NOISE_BASELINE_THRESHOLD, _ALERT_NOISE_TREATMENT_THRESHOLD}
                ),
            )
            or not _pilot_rule_is_safe(
                after,
                allowed_thresholds=frozenset(
                    {_ALERT_NOISE_BASELINE_THRESHOLD, _ALERT_NOISE_TREATMENT_THRESHOLD}
                ),
            )
            or {_pilot_threshold(before), _pilot_threshold(after)}
            != {_ALERT_NOISE_BASELINE_THRESHOLD, _ALERT_NOISE_TREATMENT_THRESHOLD}
            or _without_pilot_threshold(before) != _without_pilot_threshold(after)
        ):
            raise ValueError(
                "Alert-noise pilot treatment or recovery must change only threshold 0 and 101"
            )
        return
    raise ValueError(
        "Alert-noise pilot plan must create or delete the pair, or update only the rule threshold"
    )


def _primary_replacement_is_exact(
    plan: dict[str, Any], resolved_models: dict[str, Any] | None
) -> bool:
    if resolved_models is None:
        raise ValueError("Core-model-quorum replacement requires resolved models")
    capabilities = resolved_models.get("capabilities")
    if not isinstance(capabilities, list):
        raise ValueError("resolved model capabilities must be an array")
    target = next(
        (
            item
            for item in capabilities
            if isinstance(item, dict) and item.get("name") == "t2.reasoner.primary"
        ),
        None,
    )
    change = next(
        item for item in plan["resource_changes"] if item.get("address") == _PRIMARY_REASONER
    ).get("change", {})
    before = change.get("before")
    after = change.get("after")
    if not isinstance(target, dict) or not isinstance(before, dict) or not isinstance(after, dict):
        return False
    before_model = before.get("model")
    after_model = after.get("model")
    before_sku = before.get("sku")
    after_sku = after.get("sku")
    if not all(
        isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict)
        for value in (before_model, after_model, before_sku, after_sku)
    ):
        return False
    return (
        change.get("actions") == ["delete", "create"]
        and before_model[0].get("name") == "gpt-4o"
        and before_model[0].get("version") == "2024-11-20"
        and before_sku[0].get("name") == "GlobalStandard"
        and before_sku[0].get("capacity") == 1
        and after_model[0].get("name") == target.get("family")
        and after_model[0].get("version") == target.get("version")
        and after_sku[0].get("name") == target.get("sku")
        and after_sku[0].get("capacity") == target.get("capacity_tpm", 0) // 1000
    )


def enforce(
    plan: dict[str, Any],
    *,
    mode: str,
    resolved_models: dict[str, Any] | None = None,
    active_model_digest: str = "",
    expected_deploy_principal_id: str = "",
) -> frozenset[str]:
    """Reject changes outside the selected bounded deployment mode."""
    changed = changed_addresses(plan)
    if mode == "deploy-identity":
        validate_deploy_identity_plan(
            plan,
            expected_principal_id=expected_deploy_principal_id,
        )
        return changed
    if mode == "design-mocks":
        allowed = _DESIGN_MOCKS
        label = "Design-mocks-only"
    elif mode == "core-model-quorum":
        if not changed:
            return changed
        if changed == frozenset({_PRIMARY_REASONER}):
            if not _primary_replacement_is_exact(plan, resolved_models):
                raise ValueError("Core-model-quorum primary replacement does not match the profile")
            return changed
        if changed != _CORE_MODEL_QUORUM:
            raise ValueError(
                "Core-model-quorum plan must change exactly the required resources: "
                + ", ".join(sorted(_CORE_MODEL_QUORUM))
            )
        account = next(
            change
            for change in plan["resource_changes"]
            if change.get("address")
            == "module.llm_azure_openai[0].azurerm_cognitive_account.primary"
        )
        if account.get("change", {}).get("actions") != ["update"]:
            raise ValueError("Core-model-quorum account prerequisite must be an in-place update")
        for change in plan["resource_changes"]:
            if (
                change.get("address") in _CORE_MODEL_QUORUM
                and change.get("address")
                != "module.llm_azure_openai[0].azurerm_cognitive_account.primary"
                and change.get("change", {}).get("actions") != ["create"]
            ):
                raise ValueError(
                    "Core-model-quorum deployments must be create-only before convergence"
                )
        return changed
    elif mode == "monitoring":
        unexpected = sorted(
            address for address in changed if not address.startswith("module.monitoring[")
        )
        if unexpected:
            raise ValueError(
                "Monitoring-only plan contains changes outside module.monitoring: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "alert-noise-pilot":
        _validate_alert_noise_pilot(plan, changed)
        return changed
    elif mode == "rca-reader-identity":
        unexpected = sorted(changed.difference(_RCA_READER_IDENTITY))
        if unexpected:
            raise ValueError(
                "RCA-reader-identity plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "observability-analyzer":
        unexpected = sorted(changed.difference(_OBSERVABILITY_ANALYZER))
        if unexpected:
            raise ValueError(
                "Observability-analyzer plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "provider-schema":
        unexpected = sorted(changed.difference(_PROVIDER_SCHEMA))
        if unexpected:
            raise ValueError(
                "Provider-schema plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "runtime-call-evidence":
        unexpected = sorted(changed.difference(_RUNTIME_CALL_EVIDENCE))
        if unexpected:
            raise ValueError(
                "Runtime-call-evidence plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "cost-governance":
        unexpected = sorted(changed.difference(_COST_GOVERNANCE))
        if unexpected:
            raise ValueError(
                "Cost Governance plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "operational-history":
        unexpected = sorted(
            address
            for address in changed
            if not any(address.startswith(prefix) for prefix in _OPERATIONAL_HISTORY_PREFIXES)
        )
        if unexpected:
            raise ValueError(
                "Operational-history plan contains changes outside its bounded scope: "
                + ", ".join(unexpected)
            )
        return changed
    elif mode == "model-binding":
        if resolved_models is None:
            raise ValueError("model-binding mode requires resolved models")
        allowed = _model_addresses(resolved_models)
        label = "Model-binding-only"
        if not changed:
            if not re.fullmatch(r"[0-9a-f]{64}", active_model_digest):
                raise ValueError("model-binding plan requires an active Core model digest")
            if _canonical_digest(resolved_models) == active_model_digest:
                raise ValueError("model-binding plan contains no deployment or artifact change")
            return changed
    else:
        raise ValueError(f"unsupported plan scope mode: {mode}")
    unexpected = sorted(changed.difference(allowed))
    if unexpected:
        raise ValueError(
            f"{label} plan contains changes outside its bounded scope: " + ", ".join(unexpected)
        )
    return changed


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "alert-noise-pilot",
            "core-model-quorum",
            "cost-governance",
            "deploy-identity",
            "design-mocks",
            "monitoring",
            "model-binding",
            "observability-analyzer",
            "provider-schema",
            "rca-reader-identity",
            "operational-history",
            "runtime-call-evidence",
        ),
        required=True,
    )
    parser.add_argument("--resolved-models", type=Path)
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    rendered = subprocess.run(
        ["terraform", "show", "-json", plan_path.name],
        check=True,
        capture_output=True,
        text=True,
        cwd=plan_path.parent,
    ).stdout
    plan = json.loads(rendered)
    resolved = _load(args.resolved_models) if args.resolved_models else None
    try:
        changed = enforce(
            plan,
            mode=args.mode,
            resolved_models=resolved,
            active_model_digest=os.environ.get("ACTIVE_CORE_MODEL_DIGEST", ""),
            expected_deploy_principal_id=os.environ.get("DEPLOY_RUNNER_PRINCIPAL_ID", ""),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{args.mode} plan accepted: {sorted(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
