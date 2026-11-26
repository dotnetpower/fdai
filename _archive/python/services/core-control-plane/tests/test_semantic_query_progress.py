"""Core semantic query progress publication tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation.semantic_runtime import (
    _resolve_progress_observer,
    bind_semantic_query_progress_observer,
)
from fdai.core.ontology_platform.query_execution import QueryNodeProgress
from fdai_core_service.semantic_turn_consumer import _progress_mapping
from fdai_service_contracts import QueryNodeKind
from fdai_service_contracts.ontology_query import OntologyQueryNode


async def _observe(_progress: QueryNodeProgress) -> None:
    return None


async def _explicit_observe(_progress: QueryNodeProgress) -> None:
    return None


def test_progress_observer_binding_is_invocation_scoped() -> None:
    assert _resolve_progress_observer(None) is None

    with bind_semantic_query_progress_observer(_observe):
        assert _resolve_progress_observer(None) is _observe
        assert _resolve_progress_observer(_explicit_observe) is _explicit_observe

    assert _resolve_progress_observer(None) is None


def test_progress_mapping_binds_request_identity_and_actual_node() -> None:
    node = OntologyQueryNode(
        node_id="current-state-target",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json='{"object_type":"Resource"}',
        output_kind="object_set",
    )
    progress = QueryNodeProgress(
        node=node,
        status="running",
        started_at=datetime(2026, 8, 26, 11, tzinfo=UTC),
        step_index=1,
        step_total=2,
    )

    published = _progress_mapping(
        {
            "request_id": "request-1",
            "semantic_turn": {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "turn_sequence": 1,
            },
        },
        progress,
        progress_sequence=1,
    )

    assert published.request_id == "request-1"
    assert published.node_kind is QueryNodeKind.OBJECT_SET
    assert published.arguments == {"object_type": "Resource"}
    assert (published.step_index, published.step_total) == (1, 2)
    assert published.execution_authority is False
