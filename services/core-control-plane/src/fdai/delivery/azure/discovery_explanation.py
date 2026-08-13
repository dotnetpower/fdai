"""Render sanitized Azure CLI and KQL explanations from registered discovery plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.discovery import (
    DiscoveryBackend,
    DiscoveryOperationProfile,
    DiscoveryPredicate,
    DiscoveryQueryPlan,
)
from fdai_service_contracts.discovery_evidence import (
    CommandExplanation,
    command_explanation_digest,
)

from fdai.delivery.azure.discovery_profiles import AZURE_DISCOVERY_CATALOG_VERSION


@dataclass(frozen=True, slots=True)
class RenderedAzureCommand:
    """Catalog-owned display argv and optional KQL without live identifiers."""

    command_id: str
    argv: tuple[str, ...]
    kql_template: str | None


def render_command_explanation(
    *,
    plan: DiscoveryQueryPlan,
    operation: DiscoveryOperationProfile,
    validated_at: datetime,
    cli_version: str,
) -> CommandExplanation:
    """Build one digest-bound explanation from a matching registered operation."""

    if plan.operation_id != operation.operation_id:
        raise ValueError("discovery plan and operation profile MUST match")
    rendered = render_registered_azure_command(plan=plan, operation=operation)
    values: dict[str, object] = {
        "command_id": rendered.command_id,
        "catalog_version": AZURE_DISCOVERY_CATALOG_VERSION,
        "plan_digest": plan.plan_digest,
        "backend": plan.backend,
        "scope_kind": plan.scope_kind,
        "cli_argv": rendered.argv,
        "kql_template": rendered.kql_template,
        "cli_version": cli_version,
        "extension_prerequisites": (
            ("resource-graph",) if rendered.command_id.startswith("azure.arg.") else ()
        ),
        "result_limit": plan.limits.max_results,
        "max_pages": plan.limits.max_pages,
        "validation_status": "validated",
        "validated_at": validated_at,
        "substitution_instructions": ("replace.subscription-id", "replace.predicate-values"),
        "equivalent_command": plan.backend is not DiscoveryBackend.REGISTERED_CLI,
        "redacted": True,
        "execution_authority": False,
    }
    return CommandExplanation.model_validate(
        {"explanation_digest": command_explanation_digest(**values), **values}
    )


def render_registered_azure_command(
    *,
    plan: DiscoveryQueryPlan,
    operation: DiscoveryOperationProfile,
) -> RenderedAzureCommand:
    """Resolve one allowlisted template id; arbitrary command text is not accepted."""

    template_id = operation.command_template_id
    if template_id is None:
        raise ValueError("discovery operation has no registered command template")
    if template_id == "azure.arg.resource-groups.list.v1":
        kql = _render_kql(plan, table="ResourceContainers", resource_groups=True)
        return _arg_command(template_id, plan=plan, kql=kql)
    if template_id == "azure.arg.resources.list.v1":
        kql = _render_kql(plan, table="Resources", resource_groups=False)
        return _arg_command(template_id, plan=plan, kql=kql)
    if template_id == "azure.arm.resource-groups.list.v1":
        return RenderedAzureCommand(
            command_id=template_id,
            argv=(
                "az",
                "group",
                "list",
                "--subscription",
                "<subscription-id>",
                "--query",
                "<registered-query:azure.resource-groups.list.v1>",
                "--output",
                "json",
            ),
            kql_template=None,
        )
    if template_id == "azure.arm.resources.list.v1":
        return RenderedAzureCommand(
            command_id=template_id,
            argv=(
                "az",
                "resource",
                "list",
                "--subscription",
                "<subscription-id>",
                "--query",
                "<registered-query:azure.arm-resources.list.v1>",
                "--output",
                "json",
            ),
            kql_template=None,
        )
    raise LookupError(f"unknown Azure discovery command template {template_id!r}")


def _arg_command(
    command_id: str,
    *,
    plan: DiscoveryQueryPlan,
    kql: str,
) -> RenderedAzureCommand:
    return RenderedAzureCommand(
        command_id=command_id,
        argv=(
            "az",
            "graph",
            "query",
            "--subscriptions",
            "<subscription-id>",
            "--graph-query",
            f"<registered-kql:{command_id}>",
            "--first",
            str(plan.limits.max_results),
            "--output",
            "json",
        ),
        kql_template=kql,
    )


def _render_kql(
    plan: DiscoveryQueryPlan,
    *,
    table: str,
    resource_groups: bool,
) -> str:
    clauses = [table]
    if resource_groups:
        clauses.append("where type =~ 'microsoft.resources/subscriptions/resourcegroups'")
    for index, predicate in enumerate(plan.predicates, start=1):
        clauses.append(_predicate_template(predicate, index=index))
    clauses.extend(
        (
            "project id, type, name, subscriptionId, resourceGroup, location, tags",
            "order by id asc",
        )
    )
    return " | ".join(clauses)


def _predicate_template(predicate: DiscoveryPredicate, *, index: int) -> str:
    field = {
        "name": "name",
        "provider_type": "type",
        "resource_group": "resourceGroup",
        "location": "location",
    }.get(predicate.field.value)
    if field is None:
        raise ValueError("registered Azure command does not support this predicate field")
    placeholder = f"<predicate-{index}>"
    if predicate.operator.value == "eq":
        return f"where {field} =~ '{placeholder}'"
    if predicate.operator.value == "contains":
        return f"where {field} contains '{placeholder}'"
    if predicate.operator.value == "in":
        placeholders = ", ".join(
            f"'<predicate-{index}-{value_index}>'"
            for value_index, _value in enumerate(predicate.values, start=1)
        )
        return f"where {field} in~ ({placeholders})"
    if predicate.operator.value == "exists":
        return f"where isnotempty({field})"
    raise ValueError("registered Azure command does not support this predicate operator")


__all__ = [
    "RenderedAzureCommand",
    "render_command_explanation",
    "render_registered_azure_command",
]
