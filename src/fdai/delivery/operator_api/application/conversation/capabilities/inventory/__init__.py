"""Typed inventory query and semantic application capability.

Responsibility:
Own deterministic inventory query contracts, compilation, semantic grounding,
and provider-read coordination for conversations.

Boundary:
Accept validated prompts or typed query arguments and return bounded inventory
evidence. HTTP, SSE, authentication, history, and terminal transport stay
route-owned; value rendering stays projection-owned.

Authority and state:
Read-only and request-local. This package cannot approve, execute, promote, or
write inventory state and receives no executor identity.

Dependencies:
Inventory provider contracts, ontology/catalog semantics, and read-only
conversation inventory projections supplied by the Operator API delivery layer.

Deployment:
Runs in-process within the Operator API and creates no network boundary.
"""

from typing import TYPE_CHECKING, Any

from .query import (
    InventoryField,
    InventoryOperator,
    InventoryPredicate,
    InventoryQuery,
    InventoryQueryGrouping,
    InventoryQueryKind,
    InventoryQueryProjection,
    InventoryQueryScope,
    InventoryQuerySource,
    InventoryQueryValueGroup,
    InventoryScheduleWindow,
    inventory_query_argument_schema,
    normalize_inventory_value,
)

if TYPE_CHECKING:
    from .ontology import (
        inventory_query_function_type,
    )
    from .resource_types import (
        InventoryResourceTypeResolver,
        default_inventory_resource_type_resolver,
    )
    from .semantic_retrieval import (
        EmbeddingInventorySemanticResolver,
        InventorySemanticConfig,
        InventorySemanticKind,
        InventorySemanticMatch,
        InventorySemanticResolver,
    )
    from .service import (
        InventoryActivityProvider,
        InventoryChatTools,
        KubernetesWorkloadProvider,
    )

__all__ = [
    "EmbeddingInventorySemanticResolver",
    "InventoryActivityProvider",
    "InventoryChatTools",
    "InventoryField",
    "InventoryOperator",
    "InventoryPredicate",
    "InventoryQuery",
    "InventoryQueryGrouping",
    "InventoryQueryKind",
    "InventoryQueryProjection",
    "InventoryQueryScope",
    "InventoryQuerySource",
    "InventoryQueryValueGroup",
    "InventoryResourceTypeResolver",
    "InventoryScheduleWindow",
    "InventorySemanticConfig",
    "InventorySemanticKind",
    "InventorySemanticMatch",
    "InventorySemanticResolver",
    "KubernetesWorkloadProvider",
    "default_inventory_resource_type_resolver",
    "inventory_query_argument_schema",
    "inventory_query_function_type",
    "normalize_inventory_value",
]


def __getattr__(name: str) -> Any:
    """Load application implementations only when a facade consumer requests them."""

    if name in {
        "EmbeddingInventorySemanticResolver",
        "InventorySemanticConfig",
        "InventorySemanticKind",
        "InventorySemanticMatch",
        "InventorySemanticResolver",
    }:
        from .semantic_retrieval import (
            EmbeddingInventorySemanticResolver,
            InventorySemanticConfig,
            InventorySemanticKind,
            InventorySemanticMatch,
            InventorySemanticResolver,
        )

        return {
            "EmbeddingInventorySemanticResolver": EmbeddingInventorySemanticResolver,
            "InventorySemanticConfig": InventorySemanticConfig,
            "InventorySemanticKind": InventorySemanticKind,
            "InventorySemanticMatch": InventorySemanticMatch,
            "InventorySemanticResolver": InventorySemanticResolver,
        }[name]
    if name == "inventory_query_function_type":
        from .ontology import (
            inventory_query_function_type,
        )

        return inventory_query_function_type
    if name in {
        "InventoryResourceTypeResolver",
        "default_inventory_resource_type_resolver",
    }:
        from .resource_types import (
            InventoryResourceTypeResolver,
            default_inventory_resource_type_resolver,
        )

        return {
            "InventoryResourceTypeResolver": InventoryResourceTypeResolver,
            "default_inventory_resource_type_resolver": default_inventory_resource_type_resolver,
        }[name]
    if name in {
        "InventoryActivityProvider",
        "InventoryChatTools",
        "KubernetesWorkloadProvider",
    }:
        from .service import (
            InventoryActivityProvider,
            InventoryChatTools,
            KubernetesWorkloadProvider,
        )

        return {
            "InventoryActivityProvider": InventoryActivityProvider,
            "InventoryChatTools": InventoryChatTools,
            "KubernetesWorkloadProvider": KubernetesWorkloadProvider,
        }[name]
    raise AttributeError(name)
