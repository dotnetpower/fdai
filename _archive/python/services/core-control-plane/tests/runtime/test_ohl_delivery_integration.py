"""Operational Hypothesis Loop delivery uses existing governed runtime paths."""

from __future__ import annotations

from typing import Any, cast

from fdai.core.executor import ResourceLockManager
from fdai.delivery.direct_api_router import RoutedDirectApiExecutor
from fdai.delivery.graph_model_promotion import (
    PROMOTE_EFFECT_MODEL_ACTION_TYPE,
    GraphModelPromotionDirectApiExecutor,
    GraphModelPromotionRegistry,
)
from fdai.runtime.delivery import _build_direct_api_executor
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def test_graph_model_promotion_uses_existing_direct_api_router() -> None:
    registry = cast(GraphModelPromotionRegistry, object())

    executor = _build_direct_api_executor(
        audit_store=InMemoryStateStore(),
        resource_lock=ResourceLockManager(),
        graph_model_promotion_registry=registry,
        action_types_by_name={PROMOTE_EFFECT_MODEL_ACTION_TYPE: cast(Any, object())},
    )

    assert executor is not None
    router = cast(RoutedDirectApiExecutor, executor._executor)
    route = router.routes[PROMOTE_EFFECT_MODEL_ACTION_TYPE]
    assert isinstance(route, GraphModelPromotionDirectApiExecutor)
    assert route._registry is registry
    assert executor._allow_enforce is True
