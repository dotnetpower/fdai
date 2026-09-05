#!/usr/bin/env python3
"""Enforce bounded Terraform plan scopes for specialized deploy modes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

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
_OPERATIONAL_HISTORY_PREFIXES = (
    "module.operational_history_storage[0].",
    "azurerm_private_endpoint.operational_history_blob[0]",
    "azurerm_container_app_job.operational_history_lifecycle[0]",
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
) -> frozenset[str]:
    """Reject changes outside the selected bounded deployment mode."""
    changed = changed_addresses(plan)
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
    elif mode == "rca-reader-identity":
        unexpected = sorted(changed.difference(_RCA_READER_IDENTITY))
        if unexpected:
            raise ValueError(
                "RCA-reader-identity plan contains changes outside its bounded scope: "
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
            raise ValueError("model-binding plan contains no deployment change")
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
            "core-model-quorum",
            "design-mocks",
            "monitoring",
            "model-binding",
            "rca-reader-identity",
            "operational-history",
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
        changed = enforce(plan, mode=args.mode, resolved_models=resolved)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{args.mode} plan accepted: {sorted(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
