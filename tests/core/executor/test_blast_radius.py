"""The executor blast-radius ceiling, shared by all three execution paths.

Three executors carried a byte-identical copy of this check. These tests pin
the shared rule so a future edit cannot fix one copy and leave two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fdai.core.executor.blast_radius import blast_radius_refusal
from fdai.shared.contracts.models import (
    Action,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
)


@dataclass(frozen=True)
class _Ceiling:
    max_affected_resources: int = 5
    max_rate_per_minute: int = 10


def _action(*, count: int | None, rate: int | None = None) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=uuid4(),
        idempotency_key="example-idem",
        event_id=uuid4(),
        action_type="ops.restart-service",
        target_resource_ref="res-1",
        operation=Operation.RESTART,
        params={},
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE_GROUP,
            count=count,
            rate_per_minute=rate,
        ),
        stop_condition="target_not_healthy",
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb-99"),
        mode=Mode.SHADOW,
        citing_rules=["ops.restart-service"],
        created_at=datetime(2026, 7, 28, tzinfo=UTC),
    )


def test_an_undeclared_count_is_refused() -> None:
    """An action whose reach cannot be evaluated is not a small action."""
    refusal = blast_radius_refusal(_action(count=None), _Ceiling())

    assert refusal is not None
    assert "undeclared" in refusal


def test_a_count_over_the_ceiling_is_refused() -> None:
    refusal = blast_radius_refusal(_action(count=6), _Ceiling())

    assert refusal is not None
    assert "exceeds executor cap" in refusal


def test_a_count_at_the_ceiling_is_allowed() -> None:
    assert blast_radius_refusal(_action(count=5), _Ceiling()) is None


def test_a_rate_over_the_ceiling_is_refused() -> None:
    refusal = blast_radius_refusal(_action(count=1, rate=11), _Ceiling())

    assert refusal is not None
    assert "/min exceeds executor cap" in refusal


def test_an_undeclared_rate_is_allowed_because_count_already_bounds_it() -> None:
    assert blast_radius_refusal(_action(count=1, rate=None), _Ceiling()) is None
