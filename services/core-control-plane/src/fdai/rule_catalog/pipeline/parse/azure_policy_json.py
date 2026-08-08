"""Parser for Azure Policy built-in definitions.

Design: consumes a snapshot tree of Azure Policy JSON definitions (the
shape shipped by the ``Azure/azure-policy`` GitHub repository under
``built-in-policies/policyDefinitions/**/*.json``) and returns
:class:`~fdai.rule_catalog.pipeline.parse.parser.ParsedRule` entries
shaped for the FDAI rule schema.

Constraints:

- The Azure Policy DSL (``policyRule`` JSON) is NOT auto-translatable
  to Rego. Imported rules therefore ship with
  ``check_logic.kind = "expression"`` and a ``reference`` that points
  at the Azure Policy definition name, plus the original ``policyRule``
  preserved on the snapshot. A downstream author (upstream curator or
  fork) authors real Rego later; the imported rule stays
  ``shadow``-only until that happens.

- Every imported rule points at the ``remediate.azure-policy-managed``
  ActionType. That ActionType is authored as a fail-closed placeholder
  (``promotion_gate.min_accuracy = 1.0`` + ``max_policy_escapes = 0``)
  so an unedited imported rule cannot be promoted to enforce.

- The parser is pure and deterministic: it walks the snapshot in
  sorted order and returns rules in that order so the caller can hash
  the output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from .parser import ParsedRule, ParseError, ParseReport, ParserName

_SOURCE_ID: Final[str] = "azure_policy"

# Curated Azure resource-type -> FDAI CSP-neutral type. Unknown types
# fall through to ``azure.<sanitized-provider-slug>`` so the imported
# rule still validates without collision with FDAI-native types.
_RESOURCE_TYPE_MAP: Final[Mapping[str, str]] = {
    "Microsoft.Storage/storageAccounts": "object-storage",
    "Microsoft.Compute/virtualMachines": "compute.vm",
    "Microsoft.Compute/virtualMachineScaleSets": "compute.vm-scale-set",
    "Microsoft.Compute/disks": "disk",
    "Microsoft.Compute/snapshots": "snapshot",
    "Microsoft.Compute/galleries": "compute.gallery",
    "Microsoft.KeyVault/vaults": "secret-store",
    "Microsoft.Sql/servers": "sql-server",
    "Microsoft.Sql/servers/databases": "sql-database",
    "Microsoft.Sql/managedInstances": "sql-managed-instance",
    "Microsoft.DBforPostgreSQL/servers": "postgresql-server",
    "Microsoft.DBforPostgreSQL/flexibleServers": "postgresql-flexible",
    "Microsoft.DBforMySQL/servers": "mysql-server",
    "Microsoft.DBforMySQL/flexibleServers": "mysql-flexible",
    "Microsoft.DocumentDB/databaseAccounts": "cosmos-db",
    "Microsoft.Cache/redis": "cache",
    "Microsoft.ContainerService/managedClusters": "kubernetes-cluster",
    "Microsoft.ContainerService/managedClusters/agentPools": "kubernetes-node-pool",
    "Microsoft.ContainerRegistry/registries": "container-registry",
    "Microsoft.Network/virtualNetworks": "network.vnet",
    "Microsoft.Network/networkSecurityGroups": "network.nsg",
    "Microsoft.Network/publicIPAddresses": "network.public-ip",
    "Microsoft.Network/loadBalancers": "network.load-balancer",
    "Microsoft.Network/applicationGateways": "network.application-gateway",
    "Microsoft.Network/azureFirewalls": "network.firewall",
    "Microsoft.Network/frontDoors": "network.front-door",
    "Microsoft.Network/privateEndpoints": "network.private-endpoint",
    "Microsoft.Web/sites": "web.app-service",
    "Microsoft.Web/serverFarms": "web.app-service-plan",
    "Microsoft.OperationalInsights/workspaces": "log-workspace",
    "Microsoft.Resources/subscriptions": "subscription",
    "Microsoft.Resources/subscriptions/resourceGroups": "resource-group",
}

# Effect -> (fdai_severity, is_deny_family). Deny-family effects
# suggest higher severity by default. This is a heuristic; upstream
# curator MAY override severity on a per-rule basis.
_EFFECT_SEVERITY: Final[Mapping[str, str]] = {
    "Deny": "high",
    "DenyAction": "high",
    "Audit": "medium",
    "AuditIfNotExists": "medium",
    "DeployIfNotExists": "medium",
    "Modify": "medium",
    "Manual": "low",
    "Append": "low",
    "Disabled": "low",
}

# Category text on Azure Policy metadata -> fdai category enum.
# Anything unmapped defaults to ``security``.
_CATEGORY_MAP: Final[Mapping[str, str]] = {
    "Cost": "cost",
    "Backup": "reliability",
    "SQL": "security",
    "Storage": "security",
    "Compute": "security",
    "Network": "security",
    "Key Vault": "security",
    "Kubernetes": "security",
    "Monitoring": "compliance",
    "Automanage": "reliability",
    "Guest Configuration": "compliance",
    "Regulatory Compliance": "compliance",
    "Tags": "config_drift",
    "General": "config_drift",
}

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class AzurePolicyJsonParser:
    """Parser plugin id ``azure-policy-json``."""

    @property
    def name(self) -> ParserName:
        return ParserName.AZURE_POLICY_JSON

    def parse(self, snapshot_tree_root: Path) -> ParseReport:
        if not snapshot_tree_root.is_dir():
            raise ParseError(
                f"snapshot root does not exist or is not a directory: {snapshot_tree_root}"
            )
        rules: list[ParsedRule] = []
        # Azure/azure-policy vendors the same policy definition into
        # multiple category folders (e.g. an App Service policy shows
        # up under both `App Service/` and `Azure Government/`). The
        # policy is a single canonical definition keyed by its GUID
        # (`name` field); emitting the same GUID more than once would
        # inflate the imported tree, silently mask which id wins the
        # `guid -> id` map the initiative compiler builds, and confuse
        # any downstream consumer counting rules. Track seen GUIDs in
        # sorted-tree order and keep only the FIRST occurrence -
        # deterministic (`rglob` output is sorted upstream), so a
        # rerun produces the same subset.
        seen_guids: set[str] = set()
        for path in sorted(snapshot_tree_root.rglob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ParseError(f"{path}: not valid JSON: {exc}") from exc
            if not isinstance(doc, Mapping) or "properties" not in doc:
                # Azure/azure-policy tree contains non-policy JSONs (e.g.
                # tsconfig.json). Skip anything that does not look like a
                # policy definition rather than failing.
                continue
            guid = str(doc.get("name") or "").lower()
            if guid and guid in seen_guids:
                # Duplicate copy of a policy already emitted from an
                # earlier subtree. Skip so the caller writes exactly
                # one file per canonical GUID.
                continue
            raw = _to_rule_mapping(doc, origin=path.relative_to(snapshot_tree_root))
            if raw is None:
                continue
            if guid:
                seen_guids.add(guid)
            rules.append(ParsedRule(origin=str(path.relative_to(snapshot_tree_root)), raw=raw))
        return ParseReport(parser=ParserName.AZURE_POLICY_JSON, rules=tuple(rules))


def _to_rule_mapping(doc: Mapping[str, Any], *, origin: Path) -> Mapping[str, Any] | None:
    """Return a mapping in FDAI rule-schema shape, or ``None`` to skip."""
    props = doc.get("properties") or {}
    policy_type = props.get("policyType")
    if policy_type not in ("BuiltIn", "Static", "Custom"):
        return None
    name = doc.get("name") or props.get("displayName")
    if not isinstance(name, str) or not name:
        return None

    display_name = props.get("displayName") or name
    metadata = props.get("metadata") or {}
    azure_category = str(metadata.get("category") or "General")
    version = str(props.get("version") or metadata.get("version") or "1.0.0")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        version = "1.0.0"

    default_effect = _extract_default_effect(props)
    resource_type = _extract_resource_type(props.get("policyRule") or {})
    fdai_category = _CATEGORY_MAP.get(azure_category, "security")
    severity = _EFFECT_SEVERITY.get(default_effect, "medium")

    slug = _rule_id_from_name(name, display_name)
    rt_slug = resource_type.replace("/", ".").replace("_", "-").lower()
    fdai_id = f"azure-builtin.{rt_slug}.{slug}".lower()
    fdai_id = re.sub(r"[^a-z0-9._-]", "-", fdai_id).strip("-.")
    # Rule schema caps id at 128 characters (^[a-z0-9][a-z0-9._-]{1,127}$).
    if len(fdai_id) > 128:
        fdai_id = fdai_id[:128].rstrip(".-_")

    return {
        "schema_version": "1.0.0",
        "id": fdai_id,
        "version": version,
        "source": _SOURCE_ID,
        "severity": severity,
        "category": fdai_category,
        "resource_type": resource_type,
        "check_logic": {
            "kind": "expression",
            "reference": f"azure-policy://{name}",
        },
        "remediation": {
            "template_ref": f"remediation/azure-builtin/{name}.md",
        },
        "remediates": "remediate.azure-policy-managed",
        "parameters": {
            "azure_policy_name": name,
            "azure_policy_display_name": display_name,
            "azure_policy_effect_default": default_effect,
            "azure_policy_category": azure_category,
        },
        "provenance": {
            "source_url": (
                "https://github.com/Azure/azure-policy/blob/main/built-in-policies/"
                f"{origin.as_posix()}"
            ),
            "source_version": version,
            "resolved_ref": "0000000000000000000000000000000000000000",
            "content_hash": "sha256:" + ("0" * 64),
            "license": "MIT",
            "redistribution": "embeddable",
            "retrieved_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def _extract_default_effect(props: Mapping[str, Any]) -> str:
    parameters = props.get("parameters") or {}
    effect_def = parameters.get("effect") if isinstance(parameters, Mapping) else None
    if isinstance(effect_def, Mapping):
        default = effect_def.get("defaultValue")
        if isinstance(default, str):
            return default
    then_effect = ((props.get("policyRule") or {}).get("then") or {}).get("effect")
    if isinstance(then_effect, str) and not then_effect.startswith("["):
        return then_effect
    return "Audit"


def _extract_resource_type(policy_rule: Mapping[str, Any]) -> str:
    """Walk the policyRule tree looking for the first ``field == "type"`` equals value."""
    for path_value in _walk_type_equals(policy_rule):
        mapped = _RESOURCE_TYPE_MAP.get(path_value)
        if mapped:
            return mapped
        # Fall back: normalize any Microsoft.X/Y into azure.x.y form.
        sanitized = path_value.replace("Microsoft.", "azure.").replace("/", ".").lower()
        sanitized = re.sub(r"[^a-z0-9._-]", "-", sanitized)
        return sanitized[:80]
    return "azure.resource"


def _walk_type_equals(node: Any) -> Iterable[str]:
    if isinstance(node, Mapping):
        if node.get("field") == "type" and isinstance(node.get("equals"), str):
            yield str(node["equals"])
        for v in node.values():
            yield from _walk_type_equals(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_type_equals(item)


def _rule_id_from_name(name: str, display_name: str) -> str:
    """Build a stable, filesystem-safe slug from name + displayName.

    Prefers displayName-derived slug (human-readable) but falls back to
    the GUID name when the display slug collapses to empty.
    """
    base = display_name if display_name else name
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    if not slug or slug == "-":
        slug = re.sub(r"[^a-zA-Z0-9]+", "", name).lower()
    if _UUID_RE.match(name) and (not slug or len(slug) < 3):
        slug = name.replace("-", "")
    return slug[:100] or "policy"


__all__ = ["AzurePolicyJsonParser"]
