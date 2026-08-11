"""Four-category live Azure deployment preflight orchestration."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from .policy import azure_policy_findings
from .transport import AzureReader, PreflightError

_REQUIRED_CATEGORIES = {
    "identity_rbac",
    "policy_guardrail",
    "quota_capacity",
    "secret_config",
}
_SECRET_NAME = re.compile(r"^[A-Za-z0-9-]{1,127}$")


def run_preflight(
    profile: Mapping[str, Any],
    plan: Mapping[str, Any],
    environment: Mapping[str, Any],
    reader: AzureReader,
) -> dict[str, Any]:
    """Evaluate all required live categories and return a sanitized report."""
    live = mapping(profile.get("azure_live"), "azure_live")
    required = set(string_list(live.get("required_categories"), "required_categories"))
    if required != _REQUIRED_CATEGORIES:
        raise PreflightError("live preflight must require all supported categories")
    azure = mapping(environment.get("azure"), "environment.azure")
    subscription_id = identifier(azure.get("subscription_id"), "subscription_id")
    region = identifier(azure.get("region"), "region")
    resource_group = identifier(live.get("resource_group"), "resource_group")
    neutral_types = _planned_resource_types(profile, plan)
    findings = _static_policy_findings(profile, neutral_types)
    findings.extend(
        azure_policy_findings(
            reader,
            subscription_id=subscription_id,
            resource_group=resource_group,
            neutral_types=neutral_types,
            arm_type_map=string_map(live.get("arm_resource_type_map"), "arm_resource_type_map"),
        )
    )
    checks = [{"category": "policy_guardrail", "status": "clear"}]

    quota_checks = live.get("quota_checks")
    if not isinstance(quota_checks, list) or not quota_checks:
        raise PreflightError("quota checks are required")
    findings.extend(
        _quota_findings(
            reader,
            subscription_id=subscription_id,
            region=region,
            checks=quota_checks,
        )
    )
    checks.append({"category": "quota_capacity", "status": "clear"})

    identity = mapping(live.get("identity_rbac"), "identity_rbac")
    findings.extend(
        _rbac_findings(
            reader,
            subscription_id=subscription_id,
            principal_id=identifier(identity.get("executor_principal_id"), "principal_id"),
            event_role_id=identifier(identity.get("event_role_definition_id"), "event_role"),
            secret_role_id=identifier(identity.get("secret_role_definition_id"), "secret_role"),
        )
    )
    checks.append({"category": "identity_rbac", "status": "clear"})

    key_vault = mapping(live.get("key_vault"), "key_vault")
    findings.extend(
        _secret_findings(
            reader,
            vault_endpoint=vault_endpoint(key_vault.get("vault_endpoint")),
            secret_names=string_list(
                key_vault.get("required_secret_names"), "required_secret_names"
            ),
        )
    )
    checks.append({"category": "secret_config", "status": "clear"})
    findings.sort(key=lambda item: str(item["id"]))
    blocked_categories = {str(finding["category"]) for finding in findings}
    for check in checks:
        if check["category"] in blocked_categories:
            check["status"] = "blocked"
    blocked = bool(findings) and profile.get("mode") == "enforce"
    return {
        "schema_version": "fdai.deployment-cli.preflight.v1",
        "report": {
            "verdict": "blocked" if findings else "clear",
            "blocks_deploy": blocked,
            "checks": checks,
            "findings": findings,
        },
    }


def _planned_resource_types(profile: Mapping[str, Any], plan: Mapping[str, Any]) -> tuple[str, ...]:
    type_map = string_map(profile.get("terraform_resource_type_map"), "terraform_resource_type_map")
    result = set(string_list(profile.get("resource_types", []), "resource_types"))
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise PreflightError("Terraform plan resource changes are invalid")
    missing: set[str] = set()
    for entry in changes:
        if not isinstance(entry, Mapping) or entry.get("mode", "managed") != "managed":
            continue
        change = entry.get("change")
        actions = change.get("actions", []) if isinstance(change, Mapping) else []
        if "create" not in actions:
            continue
        resource_type = entry.get("type")
        if resource_type == "terraform_data":
            continue
        if not isinstance(resource_type, str) or resource_type not in type_map:
            missing.add(str(resource_type))
            continue
        result.add(type_map[resource_type])
    if missing:
        raise PreflightError("Terraform resource type mapping is incomplete")
    return tuple(sorted(result))


def _static_policy_findings(
    profile: Mapping[str, Any], neutral_types: tuple[str, ...]
) -> list[dict[str, Any]]:
    policy = mapping(profile.get("policy"), "policy")
    denied = set(string_list(policy.get("denied_resource_types", []), "denied types"))
    blocked_hosts = set(string_list(policy.get("blocked_egress_hosts", []), "blocked hosts"))
    target_hosts = set(string_list(profile.get("egress_hosts", []), "egress_hosts"))
    findings = [
        finding(
            identifier_value=f"static-policy:{resource_type}",
            category="policy_guardrail",
            title="a planned resource type is denied by the supplied policy",
        )
        for resource_type in sorted(set(neutral_types) & denied)
    ]
    findings.extend(
        finding(
            identifier_value=f"static-egress:{hashlib.sha256(host.encode()).hexdigest()[:16]}",
            category="policy_guardrail",
            title="a required egress destination is denied by the supplied policy",
        )
        for host in sorted(target_hosts & blocked_hosts)
    )
    return findings


def _quota_findings(
    reader: AzureReader,
    *,
    subscription_id: str,
    region: str,
    checks: list[Any],
) -> list[dict[str, Any]]:
    usages = reader.get_values(
        f"/subscriptions/{subscription_id}/providers/Microsoft.Compute/locations/{region}/usages",
        api_version="2023-07-01",
    )
    indexed: dict[str, tuple[int, int]] = {}
    for usage in usages:
        name = usage.get("name")
        value = name.get("value") if isinstance(name, Mapping) else None
        current = usage.get("currentValue")
        limit = usage.get("limit")
        if (
            isinstance(value, str)
            and isinstance(current, (int, float))
            and not isinstance(current, bool)
            and isinstance(limit, (int, float))
            and not isinstance(limit, bool)
        ):
            indexed[value.casefold()] = (int(current), int(limit))
    findings: list[dict[str, Any]] = []
    for raw_check in checks:
        check = mapping(raw_check, "quota check")
        name = identifier(check.get("quota_name"), "quota_name")
        required = check.get("required", 1)
        if not isinstance(required, int) or isinstance(required, bool) or required < 1:
            raise PreflightError("quota requirement is invalid")
        usage = indexed.get(name.casefold())
        if usage is not None and usage[0] + required > usage[1]:
            findings.append(
                finding(
                    identifier_value=f"quota:{name}@{region}",
                    category="quota_capacity",
                    title="required Azure quota headroom is unavailable",
                )
            )
    return findings


def _rbac_findings(
    reader: AzureReader,
    *,
    subscription_id: str,
    principal_id: str,
    event_role_id: str,
    secret_role_id: str,
) -> list[dict[str, Any]]:
    rows = reader.query_role_assignments(subscription_id=subscription_id, principal_id=principal_id)
    event_found = False
    secret_found = False
    for row in rows:
        role = str(row.get("roleDefinitionId") or "").casefold()
        scope = str(row.get("scope") or "").casefold()
        event_found = event_found or role.endswith(event_role_id.casefold())
        secret_found = secret_found or (
            role.endswith(secret_role_id.casefold())
            and "/providers/microsoft.keyvault/vaults/" in scope
        )
    findings = []
    if not event_found:
        findings.append(
            finding(
                identifier_value="missing-executor-role:event-bus-data-owner",
                category="identity_rbac",
                title="executor event bus role is missing",
            )
        )
    if not secret_found:
        findings.append(
            finding(
                identifier_value="missing-executor-role:secret-reader",
                category="identity_rbac",
                title="executor secret role is missing",
            )
        )
    return findings


def _secret_findings(
    reader: AzureReader, *, vault_endpoint: str, secret_names: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not secret_names or len(secret_names) > 64:
        raise PreflightError("required secret names are invalid")
    findings = []
    for name in sorted(set(secret_names)):
        if _SECRET_NAME.fullmatch(name) is None:
            raise PreflightError("required secret name is invalid")
        status = reader.secret_status(vault_endpoint=vault_endpoint, secret_name=name)
        if status == 404:
            reference = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
            findings.append(
                finding(
                    identifier_value=f"missing-secret-ref:{reference}",
                    category="secret_config",
                    title="a required secret reference is missing",
                )
            )
        elif status >= 400:
            raise PreflightError("Key Vault secret metadata read failed")
    return findings


def finding(*, identifier_value: str, category: str, title: str) -> dict[str, Any]:
    return {
        "id": identifier_value,
        "category": category,
        "severity": "blocking",
        "title": title,
    }


def mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreflightError(f"{name} is invalid")
    return value


def string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise PreflightError(f"{name} is invalid")
    return tuple(value)


def string_map(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise PreflightError(f"{name} is invalid")
    return dict(value)


def identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "'" in value or len(value) > 256:
        raise PreflightError(f"{name} is invalid")
    return value.strip()


def vault_endpoint(value: Any) -> str:
    endpoint = identifier(value, "vault_endpoint")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not parsed.hostname.endswith(".vault.azure.net")
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise PreflightError("vault_endpoint is invalid")
    return endpoint
