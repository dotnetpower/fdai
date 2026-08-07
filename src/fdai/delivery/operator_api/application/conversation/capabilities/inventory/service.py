"""Deterministic Azure inventory evidence and answers for Command Deck."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from fdai.delivery.operator_api.application.conversation.capabilities.inventory.compiler import (
    compile_inventory_query,
    inventory_query_requires_semantic_completion,
    inventory_query_scope,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.contracts import (
    InventoryGraphProvider,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.followup import (
    SUBSCRIPTION_ROOT,
    SUBSCRIPTION_ROOT_LIMIT,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.language import (
    default_inventory_query_language_resolver,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.query import (
    InventoryQuery,
    InventoryQueryKind,
    InventoryQueryScope,
    InventoryQuerySource,
    inventory_query_argument_schema,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.semantics import (
    SemanticInventoryStatusError,
    canonicalize_semantic_inventory_status_arguments,
    ground_inventory_status_query,
)
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    ChatToolResolver,
)
from fdai.delivery.operator_api.application.conversation.intents import is_topology_question
from fdai.delivery.operator_api.application.conversation.turn_plan import TurnTool
from fdai.delivery.operator_api.projections.conversation.inventory.activity import (
    MAX_ACTIVITY_EVENTS,
)
from fdai.delivery.operator_api.projections.conversation.inventory.projection import (
    _inventory_interpretation_required,
    _project_inventory_result,
    _project_verified_inventory_result,
    _safe_inventory_payload,
    needs_inventory_evidence,
)
from fdai.delivery.operator_api.projections.conversation.inventory.schedule import (
    schedule_reference_is_current,
)

from .resource_types import (
    default_inventory_resource_type_resolver,
)
from .semantic_retrieval import (
    InventorySemanticResolver,
)

KubernetesWorkloadProvider = Callable[[], Awaitable[Mapping[str, Any]]]
InventoryActivityProvider = Callable[[int, int], Awaitable[Mapping[str, Any]]]
InventoryClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@runtime_checkable
class InventoryRefreshBarrier(Protocol):
    async def wait_for_refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InventoryChatTools:
    """Resolve Azure resource questions from the authoritative graph provider."""

    provider: InventoryGraphProvider
    fallback: ChatToolResolver | None = None
    workload_provider: KubernetesWorkloadProvider | None = None
    activity_provider: InventoryActivityProvider | None = None
    semantic_resolver: InventorySemanticResolver | None = None
    clock: InventoryClock = _utc_now

    def turn_tools(self) -> tuple[TurnTool, ...]:
        """Return the strict semantic capability for generalized resource reads."""

        return (
            TurnTool(
                name="query_inventory",
                description=(
                    "Read current resources or bounded resource changes with verified predicates."
                ),
                side_effect_class="read",
                argument_schema=inventory_query_argument_schema(),
            ),
        )

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        """Execute one verified semantic inventory plan without reclassifying text."""

        del principal_id
        if tool_name != "query_inventory":
            return None
        query = InventoryQuery.from_mapping(arguments)
        if (
            query.kind is InventoryQueryKind.SCHEDULED_SHUTDOWN
            and not schedule_reference_is_current(query, self.clock())
        ):
            return {
                "tool": "query_inventory",
                "authority": "server_inventory_graph",
                "result": {
                    "status": "unavailable",
                    "reason": "scheduled_shutdown_reference_time_stale",
                    "query": query.to_dict(),
                },
            }
        try:
            query = canonicalize_semantic_inventory_status_arguments(query, arguments)
        except SemanticInventoryStatusError:
            return {
                "tool": "query_inventory",
                "authority": "server_inventory_graph",
                "result": {
                    "status": "unavailable",
                    "reason": "inventory_semantic_status_invalid",
                },
            }
        return await self._resolve_query(query)

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if is_topology_question(prompt):
            return {
                "tool": "query_inventory",
                "authority": "server_inventory_graph",
                "result": {
                    "status": "unavailable",
                    "reason": "topology_selector_required",
                },
            }
        semantic_hold = await self._semantic_hold(prompt)
        if semantic_hold is not None:
            return semantic_hold
        if not needs_inventory_evidence(prompt):
            return await self._fallback(prompt, principal_id=principal_id)
        try:
            graph = await self._graph_for_scope(inventory_query_scope(prompt))
            safe_payload = _safe_inventory_payload(graph)
            if safe_payload is None:
                raise ValueError("invalid_inventory_payload")
            resources, raw_links = safe_payload
            managed = [item for item in resources if item["type"] != "subscription"]
            query = compile_inventory_query(prompt, resources=managed, now=self.clock())
            if query is None:
                return {
                    "tool": "query_inventory",
                    "authority": "server_inventory_graph",
                    "result": {
                        "status": "unavailable",
                        "reason": "inventory_query_not_compiled",
                    },
                }
            if inventory_query_requires_semantic_completion(query, prompt=prompt):
                return {
                    "tool": "query_inventory",
                    "authority": "server_inventory_graph",
                    "result": {
                        "status": "unavailable",
                        "reason": "inventory_semantic_interpretation_required",
                        "query": query.to_dict(),
                    },
                }
            if query.require_fresh and graph.get("freshness") != "fresh":
                graph = await self._graph_for_query(query, graph=graph)
                safe_payload = _safe_inventory_payload(graph)
                if safe_payload is None:
                    raise ValueError("invalid_inventory_payload")
                resources, raw_links = safe_payload
            activity = await self._activity(query)
            if (
                query.kind is InventoryQueryKind.SCHEDULED_SHUTDOWN
                and not schedule_reference_is_current(query, self.clock())
            ):
                result = {
                    "status": "unavailable",
                    "reason": "scheduled_shutdown_reference_time_stale",
                    "query": query.to_dict(),
                }
                return {
                    "tool": "query_inventory",
                    "authority": "server_inventory_graph",
                    "result": result,
                }
            result = _project_verified_inventory_result(
                query,
                graph,
                activity=activity,
                projected=(resources, raw_links),
            )
            if result.get("coverage_gap") == "kubernetes_workloads":
                result = await self._resolve_workloads(result)
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result = {"status": "unavailable", "reason": type(exc).__name__}
        return {
            "tool": "query_inventory",
            "authority": (
                "server_inventory_activity"
                if result.get("query_source") == InventoryQuerySource.ACTIVITY.value
                else "server_inventory_graph"
            ),
            "result": result,
        }

    async def _semantic_hold(self, prompt: str) -> dict[str, Any] | None:
        language = default_inventory_query_language_resolver()
        if language.has(language.registry.signals, "mutation", prompt):
            return None
        if language.has(language.registry.signals, "causal_diagnosis", prompt):
            return None
        if language.has(language.registry.signals, "diagnosis", prompt):
            return None
        resource_types = default_inventory_resource_type_resolver().resolve(prompt)
        if not resource_types:
            return None
        query = compile_inventory_query(prompt, now=self.clock())
        if query is not None and not inventory_query_requires_semantic_completion(
            query, prompt=prompt
        ):
            return None
        if self.semantic_resolver is None:
            return _inventory_interpretation_required(query) if query is not None else None
        candidates = await self.semantic_resolver.resolve(prompt)
        if not candidates:
            return _inventory_interpretation_required(query) if query is not None else None
        return {
            "tool": "query_inventory",
            "authority": "server_inventory_graph",
            "result": {
                "status": "clarification",
                "reason": "inventory_semantic_confirmation_required",
                "query": query.to_dict() if query is not None else None,
                "resource_types": list(resource_types),
                "semantic_candidates": [candidate.to_dict() for candidate in candidates],
            },
        }

    async def _resolve_query(
        self,
        query: InventoryQuery,
        *,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        graph = await self._graph_for_query(query)
        projected = _safe_inventory_payload(graph)
        if projected is not None:
            resources, _links = projected
            query = ground_inventory_status_query(query, resources)
        activity = await self._activity(query)
        result = (
            _project_inventory_result(prompt, graph, activity=activity)
            if prompt is not None
            else _project_verified_inventory_result(query, graph, activity=activity)
        )
        return {
            "tool": "query_inventory",
            "authority": (
                "server_inventory_activity"
                if query.source is InventoryQuerySource.ACTIVITY
                else "server_inventory_graph"
            ),
            "result": result,
        }

    async def _graph_for_query(
        self,
        query: InventoryQuery,
        *,
        graph: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        graph = graph or await self._graph_for_scope(query.scope)
        if query.require_fresh and graph.get("freshness") != "fresh":
            if isinstance(self.provider, InventoryRefreshBarrier):
                await self.provider.wait_for_refresh()
                graph = await self._graph_for_scope(query.scope)
            if graph.get("freshness") != "fresh":
                return {
                    **graph,
                    "resources": [],
                    "links": [],
                    "freshness": str(graph.get("freshness") or "unknown"),
                    "unavailable_reason": "fresh_inventory_required",
                }
        return graph

    async def _graph_for_scope(self, scope: InventoryQueryScope) -> dict[str, Any]:
        if scope is InventoryQueryScope.SUBSCRIPTION:
            graph = dict(
                await self.provider(
                    None,
                    4,
                    ("contains", "attached_to", "depends_on"),
                    root=SUBSCRIPTION_ROOT,
                    limit=SUBSCRIPTION_ROOT_LIMIT,
                )
            )
        else:
            graph = dict(await self.provider(None, 4, ("contains", "attached_to", "depends_on")))
        return graph

    async def _activity(self, query: InventoryQuery) -> Mapping[str, Any] | None:
        if query.source is not InventoryQuerySource.ACTIVITY:
            return None
        if self.activity_provider is None:
            return {"status": "unavailable", "reason": "activity_provider_unavailable"}
        return dict(
            await self.activity_provider(
                query.lookback_seconds or 0,
                MAX_ACTIVITY_EVENTS,
            )
        )

    async def _resolve_workloads(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.workload_provider is None:
            return result
        try:
            workload = dict(await self.workload_provider())
        except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
            result["workload_evidence_status"] = "unavailable"
            result["workload_evidence_reason"] = type(exc).__name__
            return result
        cluster_names = {
            str(item.get("name"))
            for item in result.get("resources", ())
            if isinstance(item, Mapping) and item.get("type") == "kubernetes-cluster"
        }
        if workload.get("status") != "matched" or workload.get("cluster_name") not in cluster_names:
            result["workload_evidence_status"] = "unmatched"
            return result
        if not isinstance(workload.get("deployments"), (list, tuple)) or not isinstance(
            workload.get("pods"), (list, tuple)
        ):
            result["workload_evidence_status"] = "invalid"
            return result
        result["workload"] = workload
        uncovered_cluster_count = len(cluster_names - {str(workload["cluster_name"])})
        if uncovered_cluster_count or bool(workload.get("truncated")):
            result["workload_evidence_status"] = "partial"
            result["uncovered_cluster_count"] = uncovered_cluster_count
            return result
        result["status"] = "matched"
        result["coverage_gap"] = None
        return result

    async def _fallback(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if self.fallback is None:
            return None
        return await self.fallback.resolve(prompt, principal_id=principal_id)


__all__ = [
    "InventoryActivityProvider",
    "InventoryChatTools",
    "InventoryRefreshBarrier",
    "KubernetesWorkloadProvider",
]
