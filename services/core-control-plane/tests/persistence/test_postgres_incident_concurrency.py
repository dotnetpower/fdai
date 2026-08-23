"""Live PostgreSQL incident lifecycle and notification concurrency tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.incident import IncidentRegistry
from fdai.delivery.persistence import (
    PostgresIncidentNotificationDeliveryStore,
    PostgresStateStore,
    PostgresStateStoreConfig,
)
from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState
from fdai.shared.providers.state_store import IncidentWriteConflictError

pytestmark = pytest.mark.integration
REPO_ROOT = Path(__file__).resolve().parents[4]


def _dsn() -> str:
    url = os.environ.get("FDAI_DATABASE_URL")
    if not url:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade_head() -> None:
    result = subprocess.run(  # noqa: S603 - controlled repository command
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_conflicting_replica_transitions_have_one_postgres_winner() -> None:
    dsn = _dsn()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    unique = uuid.uuid4().hex
    first = IncidentRegistry(state_store=store)
    incident = await first.open(
        correlation_keys=(f"resource:integration-{unique}",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(uuid.uuid4(),),
        actor_oid="Heimdall",
    )
    second = IncidentRegistry(state_store=store)
    second.rehydrate(await store.read_incident_transitions())

    results = await asyncio.gather(
        first.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.TRIAGING,
            actor_oid="operator-a",
        ),
        second.transition(
            incident_id=incident.incident_id,
            to_state=IncidentState.MITIGATED,
            actor_oid="operator-b",
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(result, Incident) for result in results) == 1
    assert sum(isinstance(result, IncidentWriteConflictError) for result in results) == 1
    restored = IncidentRegistry(state_store=store)
    restored.rehydrate(await store.read_incident_transitions())
    assert restored.get(incident.incident_id) is not None


async def test_postgres_incident_numbers_are_duplicate_safe_and_unique() -> None:
    dsn = _dsn()
    _upgrade_head()
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    unique = uuid.uuid4().hex
    opened_at = datetime(2099, 12, 1, tzinfo=UTC)
    numbered_at = datetime(2026, 8, 24, tzinfo=UTC)
    first_registry = IncidentRegistry(state_store=store, number_clock=lambda: numbered_at)
    duplicate_registry = IncidentRegistry(state_store=store, number_clock=lambda: numbered_at)

    first, duplicate = await asyncio.gather(
        first_registry.open(
            correlation_keys=(f"resource:integration-{unique}",),
            severity=IncidentSeverity.SEV2,
            member_event_ids=(uuid.uuid4(),),
            actor_oid="Heimdall",
            opened_at=opened_at,
        ),
        duplicate_registry.open(
            correlation_keys=(f"resource:integration-{unique}",),
            severity=IncidentSeverity.SEV2,
            member_event_ids=(uuid.uuid4(),),
            actor_oid="Heimdall",
            opened_at=opened_at,
        ),
    )
    second = await first_registry.open(
        correlation_keys=(f"resource:integration-{unique}-second",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(uuid.uuid4(),),
        actor_oid="Heimdall",
        opened_at=opened_at,
    )

    assert first.incident_number == duplicate.incident_number
    assert first.incident_number is not None
    assert first.incident_number.startswith("INC-202608-")
    assert second.incident_number is not None
    assert second.incident_number.startswith("INC-202608-")
    assert second.incident_number != first.incident_number


async def test_notification_claim_has_one_postgres_winner() -> None:
    dsn = _dsn()
    _upgrade_head()
    store = PostgresIncidentNotificationDeliveryStore(config=PostgresStateStoreConfig(dsn=dsn))
    audit_id = f"integration-notice-{uuid.uuid4()}"
    now = datetime.now(tz=UTC)

    claims = await asyncio.gather(
        *(store.claim(audit_id=audit_id, now=now, lease_seconds=60) for _ in range(8))
    )

    assert sum(claim.status.value == "claimed" for claim in claims) == 1
    assert sum(claim.status.value == "in_progress" for claim in claims) == 7
