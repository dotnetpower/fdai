"""Pure value validation and projection for standalone deployment checkpoints."""

from __future__ import annotations

import hashlib
import re

from fdai_deployment_cli.contracts import canonical_digest


def plan_summary(value: object) -> dict[str, object]:
    """Project one bounded Terraform plan into review-safe action counts and addresses."""
    changes = value.get("resource_changes") if isinstance(value, dict) else None
    if not isinstance(changes, list) or len(changes) > 5000:
        raise ValueError("Terraform plan resource change inventory is invalid")
    counts = {name: 0 for name in ("create", "update", "delete", "replace", "read", "no-op")}
    types: dict[str, int] = {}
    projected: list[dict[str, object]] = []
    for item in changes:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("type"), str)
            or not isinstance(item.get("address"), str)
            or not item["address"]
        ):
            raise ValueError("Terraform plan resource change is invalid")
        change = item.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
            raise ValueError("Terraform plan action is invalid")
        action_set = set(actions)
        if action_set == {"create", "delete"}:
            counts["replace"] += 1
        else:
            for action in action_set:
                if action in counts:
                    counts[action] += 1
        resource_type = str(item["type"])
        types[resource_type] = types.get(resource_type, 0) + 1
        projected.append({"address": item["address"], "actions": actions})
    return {
        "action_counts": counts,
        "resource_type_counts": dict(sorted(types.items())),
        "resource_changes": projected,
    }


def required_image_digest(records: dict[str, object], name: str) -> str:
    """Return one exact OCI image digest from a validated runtime record."""
    record = records.get(name)
    if not isinstance(record, dict) or any(not isinstance(key, str) for key in record):
        raise ValueError(f"runtime image {name} is invalid")
    digest = record.get("image_digest")
    if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        raise ValueError("runtime image digest is invalid")
    return digest


def foundation_binding_digest(
    handoff: dict[str, object],
    *,
    runner: dict[str, object],
    state: dict[str, object],
    ops: dict[str, object],
    app: dict[str, object],
) -> str:
    """Bind the selected Foundation resources to the exact source handoff."""
    return canonical_digest(
        {
            "source_commit": handoff.get("source_commit"),
            "run_digest": handoff.get("run_digest"),
            "region": handoff.get("region"),
            "region_short": handoff.get("region_short"),
            "runner": runner,
            "state": state,
            "ops": ops,
            "app_resource_group": app,
        }
    )


def foundation_application_workload(
    app: dict[str, object], *, environment: str, region_short: str
) -> str:
    """Recover the bounded workload token from one reviewed resource-group name."""
    name = app.get("name")
    suffix = f"-{environment}-{region_short}"
    if not isinstance(name, str) or not name.startswith("rg-") or not name.endswith(suffix):
        raise ValueError("Foundation application resource-group name is invalid")
    workload = name[3 : -len(suffix)]
    if re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None:
        raise ValueError("Foundation application workload is invalid")
    return workload


def vault_name(uri: str) -> str:
    """Extract one bounded public-cloud Key Vault name from its exact HTTPS URI."""
    match = re.fullmatch(r"https://([a-z0-9-]{3,24})[.]vault[.]azure[.]net/?", uri)
    if match is None:
        raise ValueError("Terraform Key Vault URI is invalid")
    return match.group(1)


def planned_container_registry_name(
    *, workload: str, environment: str, region_short: str, resource_suffix: str
) -> str:
    """Return the exact container registry name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
        or re.fullmatch(r"[0-9a-f]{6}", resource_suffix) is None
    ):
        raise ValueError("planned container registry name inputs are invalid")
    return f"cr{workload}{environment.replace('-', '')}{region_short}{resource_suffix}"


def planned_key_vault_name(
    *, workload: str, environment: str, region_short: str, resource_suffix: str
) -> str:
    """Return the exact Key Vault name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
        or re.fullmatch(r"[0-9a-f]{6}", resource_suffix) is None
    ):
        raise ValueError("planned Key Vault name inputs are invalid")
    full_name = f"kv-{workload}-{environment}-{region_short}-{resource_suffix}"
    return (
        full_name
        if len(full_name) <= 24
        else f"kv-aip-{hashlib.sha256(full_name.encode()).hexdigest()[:8]}"
    )


def planned_document_storage_name(
    *, subscription_id: str, workload: str, environment: str, region_short: str
) -> str:
    """Return the exact document-storage name rendered by the verified Terraform root."""

    if (
        re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription_id)
        is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,11}", workload) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{1,15}", environment) is None
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
    ):
        raise ValueError("planned document storage name inputs are invalid")
    unique = hashlib.md5(
        f"{subscription_id.casefold()}:{environment}".encode(), usedforsecurity=False
    ).hexdigest()[:6]
    return f"st{workload}doc{environment}{region_short}{unique}"[:24]


def console_origin(hostname: str) -> str:
    """Return the HTTPS origin for one deployed Static Web App hostname."""
    if (
        re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:[.][0-9]+)?[.]azurestaticapps[.]net",
            hostname,
        )
        is None
    ):
        raise ValueError("Console Static Web App hostname is invalid")
    return f"https://{hostname}"
