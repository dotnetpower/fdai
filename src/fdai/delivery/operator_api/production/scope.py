"""Production effective-scope composition from deployment environment."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.delivery.operator_api.routes.scope import StaticScopeSource, build_scope_view
from fdai.rule_catalog.schema.scope import ScopeBinding, ScopeRef


def build_production_scope_source(env: Mapping[str, str]) -> StaticScopeSource | None:
    """Build the deployed subscription/RG boundary without repository values."""

    subscription = env.get("AZURE_SUBSCRIPTION_ID", "").strip()
    resource_group = env.get("AZURE_RESOURCE_GROUP", "").strip()
    if not subscription and not resource_group:
        return None
    if not subscription or not resource_group:
        raise ValueError(
            "AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP MUST be configured together"
        )
    subscription_ref = ScopeRef(("azure", subscription))
    resource_group_ref = ScopeRef(("azure", subscription, resource_group))
    return StaticScopeSource(
        build_scope_view(
            monitoring=ScopeBinding(includes=(subscription_ref,)),
            action=ScopeBinding(includes=(resource_group_ref,)),
            executor_resource_groups=(resource_group,),
            executor_note="The executor identity cannot act outside this resource-group boundary.",
        )
    )


__all__ = ["build_production_scope_source"]
