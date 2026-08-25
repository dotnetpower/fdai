#!/usr/bin/env python3
"""Enforce bounded Terraform plan scopes for specialized deploy modes."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

_DESIGN_MOCKS = frozenset({"module.design_mocks[0].azurerm_static_web_app.design_mocks"})


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
        choices=("design-mocks", "monitoring", "model-binding"),
        required=True,
    )
    parser.add_argument("--resolved-models", type=Path)
    args = parser.parse_args()
    rendered = subprocess.run(
        ["terraform", "show", "-json", str(args.plan)],
        check=True,
        capture_output=True,
        text=True,
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
