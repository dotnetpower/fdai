"""Project exact Azure Container Apps ingress into generic verified fields."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.resource_ingress_queries import (
    RESOURCE_INGRESS_FUNCTION_NAME,
)
from fdai.shared.contracts.models import OntologyDeclarationKind, OntologyRelease

_CONTAINER_APP_TYPE = "compute.container-app"
_MAX_TRAFFIC_RULES = 16


def semantic_resource_ingress_function(
    ontology_release: OntologyRelease,
) -> ContextualOntologyFunction:
    """Return allowlisted ingress fields from one exact secured Container App."""

    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_INGRESS_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != ("operations-review",):
            raise PermissionError("resource ingress purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        objects = secured.materialization.graph.objects
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, reason="target_resolution_incomplete")
        if len(objects) != 1:
            return _table((), complete=False, reason="target_resolution_not_exact")
        target = objects[0]
        if _text(target.properties.get("type")) != _CONTAINER_APP_TYPE:
            return _table((), complete=False, reason="target_type_not_container_app")
        provider = _mapping(target.properties.get("properties"))
        source_fact = _mapping(provider.get("_state_fact"))
        source_observed_at = _text(source_fact.get("effective_at"))
        state = _mapping(provider.get("properties"))
        configuration_value = state.get("configuration")
        reasons: list[str] = []
        if provider.get("_truncated") is True:
            reasons.append("provider_properties_truncated")
        if source_observed_at is None:
            reasons.append("source_observed_at_unavailable")

        ingress: Mapping[str, Any] | None = None
        ingress_enabled: bool | None = None
        if isinstance(configuration_value, Mapping):
            ingress_value = configuration_value.get("ingress")
            if ingress_value is None:
                ingress_enabled = False
            elif isinstance(ingress_value, Mapping):
                ingress = ingress_value
                ingress_enabled = True
            else:
                reasons.append("ingress_configuration_unavailable")
        else:
            reasons.append("container_app_configuration_unavailable")

        traffic_rules, traffic_reason = _traffic_rules(
            ingress.get("traffic") if ingress is not None else None
        )
        if traffic_reason is not None:
            reasons.append(traffic_reason)
        values = {
            "name": _text(target.properties.get("name")),
            "ingress_enabled": ingress_enabled,
            "external": _boolean(ingress.get("external")) if ingress is not None else None,
            "fqdn": _text(ingress.get("fqdn")) if ingress is not None else None,
            "target_port": _integer(ingress.get("targetPort")) if ingress is not None else None,
            "transport": _text(ingress.get("transport")) if ingress is not None else None,
            "allow_insecure": (
                _boolean(ingress.get("allowInsecure")) if ingress is not None else None
            ),
            "exposed_port": (_integer(ingress.get("exposedPort")) if ingress is not None else None),
            "client_certificate_mode": (
                _text(ingress.get("clientCertificateMode")) if ingress is not None else None
            ),
            "traffic_rules": traffic_rules,
            "traffic_rule_count": len(traffic_rules),
            "custom_domain_count": (
                _list_count(ingress.get("customDomains")) if ingress is not None else 0
            ),
            "ip_security_restriction_count": (
                _list_count(ingress.get("ipSecurityRestrictions")) if ingress is not None else 0
            ),
            "active_revisions_mode": (
                _text(configuration_value.get("activeRevisionsMode"))
                if isinstance(configuration_value, Mapping)
                else None
            ),
            "source_observed_at": source_observed_at,
            "inventory_read_at": secured.receipt.observation_cutoff.isoformat(),
            "execution_authority": False,
        }
        if ingress is not None:
            for field in ("external", "target_port", "transport", "allow_insecure"):
                if values[field] is None:
                    reasons.append(f"{field}_unavailable")
        reason = "+".join(dict.fromkeys(reasons)) or None
        return _table(
            (QueryRow.from_values("resource-ingress-configuration", values),),
            complete=reason is None,
            reason=reason,
        )

    return evaluate


def _traffic_rules(value: object) -> tuple[list[dict[str, object]], str | None]:
    if value is None:
        return [], None
    if not isinstance(value, list):
        return [], "ingress_traffic_unavailable"
    rules: list[dict[str, object]] = []
    malformed = False
    for item in value[:_MAX_TRAFFIC_RULES]:
        if not isinstance(item, Mapping):
            malformed = True
            continue
        rules.append(
            {
                "revision_name": _text(item.get("revisionName")),
                "label": _text(item.get("label")),
                "weight": _integer(item.get("weight")),
                "latest_revision": _boolean(item.get("latestRevision")),
            }
        )
    if len(value) > _MAX_TRAFFIC_RULES:
        return rules, "ingress_traffic_truncated"
    return rules, "ingress_traffic_unavailable" if malformed else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _list_count(value: object) -> int | None:
    return len(value) if isinstance(value, list) else None


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=reason)
    return cast(dict[str, object], json.loads(table.canonical_json()))


__all__ = ["semantic_resource_ingress_function"]
