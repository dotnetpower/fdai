"""Family-specific shape validation for operational conversation preflight."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fdai_service_contracts.semantic_judgment import SemanticTarget

from .conversation_preflight_contracts import (
    ConversationPreflightProposal,
    OperationalPreflightFamily,
    OperationalWindowMode,
)
from .conversation_preflight_targets import named_subscription_requested

_LOGGER = logging.getLogger("fdai.core.conversation.conversation_preflight")

_INVENTORY_FACETS = frozenset(
    {"resource_inventory", "subscription", "complete_content", "download"}
)

_RESOURCE_COLLECTION_FACETS = frozenset(
    {
        "current_state",
        "list",
        "resource_collection",
        "state_change_history",
        "subscription",
    }
)

_SUBSCRIPTION_SCOPE_FACETS = frozenset({"subscription"})

_SUBSCRIPTION_SERVICE_HEALTH_FACETS = frozenset({"service_health"})

_RECENT_RESOURCE_STATE_CHANGE_FACETS = frozenset(
    {"recently_changed", "resource_count", "default_recent_window"}
)

_RECENT_RESOURCE_CHANGE_FACETS = frozenset(
    {"changed_resources", "resource_count", "default_recent_window"}
)

_RESOURCE_COLLECTION_FACET_ALIASES = {
    "resource_name_filter": "name_filter",
    "resource_state_filter": "current_state",
}

_CONFIGURATION_FACETS = frozenset(
    {
        "before_after",
        "capacity_units",
        "configuration_changes",
        "default_recent_window",
        "historical_coverage",
        "last_hour",
        "potential_issues",
        "tpm",
    }
)

_GATEWAY_FACETS = frozenset(
    {
        "apim",
        "application_gateway",
        "backend",
        "backend_connect_time",
        "backend_response_code",
        "before_after",
        "configuration_changes",
        "first_byte_time",
        "gateway_response_code",
        "gpt",
        "http_status",
        "last_byte_time",
        "last_hour",
        "latency",
        "status_429",
        "status_500",
        "status_503",
        "topology",
        "total_time",
        "default_recent_window",
    }
)

_GATEWAY_FACET_ALIASES = {
    "api_management": "apim",
    "api_management_issue": "apim",
    "gpt_family": "gpt",
    "gpt_resource_issue": "gpt",
    "gpt_service": "gpt",
    "gpt_version": "gpt",
    "http_429": "status_429",
    "http_500": "status_500",
    "http_503": "status_503",
    "resource_configuration_changes": "configuration_changes",
}


@dataclass(frozen=True, slots=True)
class OperationalFamilyValidation:
    """Validated intent and canonical facets for one operational family."""

    primary_intent: str
    normalized_facets: tuple[str, ...]


def validate_operational_family(
    proposal: ConversationPreflightProposal,
    *,
    normalized_targets: Sequence[SemanticTarget],
    utterance: str,
) -> OperationalFamilyValidation | None:
    """Validate one family-specific shape without changing target identity."""
    primary_intent = {
        OperationalPreflightFamily.INVENTORY_DOCUMENT: "create.document",
        OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES: (
            "query.resource_configuration_changes"
        ),
        OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE: (
            "query.gateway_diagnostic_evidence"
        ),
        OperationalPreflightFamily.RESOURCE_CURRENT_STATE: "query.resource_current_state",
        OperationalPreflightFamily.RECENT_RESOURCE_CHANGES: "query.resource_change_activity",
        OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES: (
            "query.resource_change_activity"
        ),
        OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY: (
            "query.subscription_scope_identity"
        ),
        OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH: (
            "query.subscription_service_health"
        ),
    }.get(proposal.operational_family)
    target_kinds = tuple(target.kind for target in normalized_targets)
    facets = frozenset(
        _RESOURCE_COLLECTION_FACET_ALIASES.get(facet, facet)
        if proposal.operational_family is OperationalPreflightFamily.RESOURCE_COLLECTION
        else facet
        for facet in proposal.operational_facets
    )
    normalized_operational_facets = proposal.operational_facets
    if proposal.operational_family is OperationalPreflightFamily.INVENTORY_DOCUMENT:
        family_valid = (
            not target_kinds
            and {"resource_inventory", "subscription"} <= facets <= _INVENTORY_FACETS
        )
        normalized_operational_facets = (
            "resource_inventory",
            "subscription",
            "complete_content",
            "download",
        )
    elif proposal.operational_family is OperationalPreflightFamily.RESOURCE_COLLECTION:
        state_filter_count = target_kinds.count("resource_state_filter") + target_kinds.count(
            "resource_state_exclusion_filter"
        )
        has_state_filter = state_filter_count == 1
        has_name_filter = target_kinds.count("resource_name_filter") == 1
        has_current_state = has_state_filter or "current_state" in facets
        expected_facets = {*_RESOURCE_COLLECTION_FACETS, "name_filter"}
        family_valid = (
            set(target_kinds)
            <= {
                "resource_type_filter",
                "resource_state_exclusion_filter",
                "resource_state_filter",
                "resource_name_filter",
            }
            and target_kinds.count("resource_type_filter") <= 1
            and state_filter_count <= 1
            and target_kinds.count("resource_name_filter") <= 1
            and len(target_kinds) == len(set(target_kinds))
            and bool(target_kinds)
            and "list" in facets
            and facets <= expected_facets
        )
        normalized_operational_facets = tuple(
            facet
            for facet in (
                "resource_collection",
                "list",
                "name_filter",
                "current_state",
                "state_change_history",
            )
            if facet in {"resource_collection", "list"}
            or (facet == "name_filter" and has_name_filter)
            or (facet == "current_state" and has_current_state)
            or (facet == "state_change_history" and facet in facets)
        )
        primary_intent = (
            "query.resource_state_inventory" if has_current_state else "query.contextual_resources"
        )
    elif proposal.operational_family is OperationalPreflightFamily.RESOURCE_CURRENT_STATE:
        family_valid = target_kinds == ("resource",) and facets == {"current_state"}
    elif proposal.operational_family is OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY:
        family_valid = (
            not target_kinds
            and facets == _SUBSCRIPTION_SCOPE_FACETS
            and not named_subscription_requested(utterance)
        )
    elif proposal.operational_family is OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH:
        family_valid = (
            not target_kinds
            and facets == _SUBSCRIPTION_SERVICE_HEALTH_FACETS
            and not named_subscription_requested(utterance)
        )
    elif proposal.operational_family is OperationalPreflightFamily.RECENT_RESOURCE_CHANGES:
        result_limit = proposal.operational_result_limit
        allowed_facets = _RECENT_RESOURCE_CHANGE_FACETS.union(
            {"limit_N", f"limit_{result_limit}"} if result_limit is not None else {"limit_N"}
        )
        normalized_operational_facets = (
            "changed_resources",
            "resource_count",
            "default_recent_window",
            f"limit_{result_limit}",
        )
        family_valid = (
            not target_kinds
            and result_limit is not None
            and proposal.operational_window
            in {OperationalWindowMode.NONE, OperationalWindowMode.SERVER_RECENT_DEFAULT}
            and {"changed_resources", "resource_count"} <= facets <= allowed_facets
        )
    elif proposal.operational_family is OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES:
        result_limit = proposal.operational_result_limit
        allowed_facets = _RECENT_RESOURCE_STATE_CHANGE_FACETS.union(
            {"limit_N", f"limit_{result_limit}"} if result_limit is not None else {"limit_N"}
        )
        normalized_operational_facets = (
            "recently_changed",
            "resource_count",
            "default_recent_window",
            f"limit_{result_limit}",
        )
        family_valid = (
            not target_kinds
            and result_limit is not None
            and proposal.operational_window
            in {OperationalWindowMode.NONE, OperationalWindowMode.SERVER_RECENT_DEFAULT}
            and {"recently_changed", "resource_count"} <= facets <= allowed_facets
        )
    elif proposal.operational_family is OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES:
        has_resource = target_kinds.count("resource") == 1
        has_resource_type = target_kinds.count("resource_type_filter") == 1
        has_time = target_kinds.count("time_range") == 1
        configuration_facets = [
            facet for facet in proposal.operational_facets if facet in _CONFIGURATION_FACETS
        ]
        normalized_configuration_facets = frozenset(configuration_facets)
        if (
            has_resource_type
            and not has_time
            and "default_recent_window" not in normalized_configuration_facets
        ):
            configuration_facets.append("default_recent_window")
        normalized_operational_facets = tuple(configuration_facets)
        normalized_configuration_facets = frozenset(configuration_facets)
        family_valid = (
            (
                (
                    has_resource
                    and not has_resource_type
                    and has_time
                    and len(target_kinds) == 2
                    and not next(
                        target.value.casefold().startswith("/subscriptions/")
                        for target in normalized_targets
                        if target.kind == "resource"
                    )
                )
                or (
                    has_resource_type
                    and not has_resource
                    and target_kinds.count("time_range") <= 1
                    and len(target_kinds) == 1 + int(has_time)
                    and (has_time or "default_recent_window" in normalized_configuration_facets)
                )
            )
            and (
                (
                    has_time
                    and proposal.operational_window
                    in {OperationalWindowMode.NONE, OperationalWindowMode.PAST_HOUR}
                )
                or (
                    not has_time
                    and (
                        proposal.operational_window
                        in {OperationalWindowMode.NONE, OperationalWindowMode.SERVER_RECENT_DEFAULT}
                        and "default_recent_window" in normalized_configuration_facets
                    )
                )
            )
            and bool(normalized_configuration_facets - {"default_recent_window", "last_hour"})
        )
    elif proposal.operational_family is OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE:
        has_time = target_kinds.count("time_range") == 1
        canonical_gateway_facets: list[str] = []
        for facet in proposal.operational_facets:
            canonical_facet = _GATEWAY_FACET_ALIASES.get(facet, facet)
            if (
                canonical_facet in _GATEWAY_FACETS
                and canonical_facet not in canonical_gateway_facets
            ):
                canonical_gateway_facets.append(canonical_facet)
        has_current_error_status = any(
            facet in {"status_429", "status_500", "status_503"}
            for facet in canonical_gateway_facets
        )
        if (
            not has_time
            and (
                proposal.operational_window is OperationalWindowMode.SERVER_RECENT_DEFAULT
                or has_current_error_status
            )
            and "default_recent_window" not in canonical_gateway_facets
        ):
            canonical_gateway_facets.append("default_recent_window")
        has_grounded_gateway_facet = bool(canonical_gateway_facets)
        normalized_operational_facets = tuple(canonical_gateway_facets)
        family_valid = (
            target_kinds.count("resource") == 1
            and target_kinds.count("time_range") <= 1
            and target_kinds.count("backend") <= 1
            and target_kinds.count("model") <= 1
            and target_kinds.count("backend") + target_kinds.count("model") <= 1
            and len(target_kinds) == len(set(target_kinds))
            and (has_time or "default_recent_window" in canonical_gateway_facets)
            and (
                (
                    has_time
                    and proposal.operational_window
                    in {OperationalWindowMode.NONE, OperationalWindowMode.PAST_HOUR}
                )
                or (
                    not has_time
                    and (
                        proposal.operational_window is OperationalWindowMode.SERVER_RECENT_DEFAULT
                        or "default_recent_window" in canonical_gateway_facets
                    )
                )
            )
            and has_grounded_gateway_facet
        )
    else:
        family_valid = False
    if (
        proposal.operational_family
        not in {
            OperationalPreflightFamily.RECENT_RESOURCE_CHANGES,
            OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES,
        }
        and proposal.operational_result_limit is not None
    ):
        family_valid = False
    if primary_intent is None or not family_valid:
        _LOGGER.info(
            "conversation_preflight_operational_shape_rejected",
            extra={
                "family": proposal.operational_family.value,
                "target_kinds": ",".join(target_kinds),
                "facets": ",".join(sorted(facets)),
            },
        )
        return None
    return OperationalFamilyValidation(
        primary_intent=primary_intent,
        normalized_facets=normalized_operational_facets,
    )
