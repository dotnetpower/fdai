from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.runtime.stewardship_identity_health import (
    StewardshipIdentityHealthWorker,
    build_stewardship_identity_health_worker,
)
from fdai.shared.providers.human_identity import HumanIdentity, StaticHumanIdentityDirectory
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "agent-stewardship.yaml"


def _stewardship():
    return load_stewardship_from_yaml(_CONFIG)


def _active_identities() -> tuple[HumanIdentity, ...]:
    stewardship = _stewardship()
    subject_ids = {
        *stewardship.maintainer_oids,
        *(
            subject.id
            for agent in stewardship.agents.values()
            for subject in agent.stewards
            if subject.kind.value == "user"
        ),
    }
    return tuple(
        HumanIdentity(
            provider="entra",
            subject_id=subject_id,
            username=f"{index}@example.invalid",
            display_name=f"Steward {index}",
        )
        for index, subject_id in enumerate(sorted(subject_ids))
    )


def _active_directory() -> StaticHumanIdentityDirectory:
    return StaticHumanIdentityDirectory(_active_identities())


async def test_health_worker_deduplicates_subjects_and_audits_only_transitions() -> None:
    store = InMemoryStateStore()
    worker = StewardshipIdentityHealthWorker(
        store=store,
        stewardship=_stewardship(),
        directory=_active_directory(),
        interval_seconds=60,
    )

    assert await worker.run_once() == "healthy"
    assert await worker.run_once() == "healthy"

    current = await store.read_state("stewardship_health:current")
    last_success = await store.read_state("stewardship_health:last_success")
    assert current is not None and current["revision"] == 1
    assert last_success is not None and last_success["status"] == "healthy"
    assert last_success["expires_at"] > last_success["checked_at"]
    assert len(store.audit_entries) == 1


async def test_health_worker_preserves_last_success_during_graph_outage() -> None:
    class UnavailableDirectory(StaticHumanIdentityDirectory):
        async def get_by_subject_id(self, subject_id: str):
            raise httpx.ConnectError("offline")

    store = InMemoryStateStore()
    healthy = StewardshipIdentityHealthWorker(
        store=store,
        stewardship=_stewardship(),
        directory=_active_directory(),
        interval_seconds=60,
    )
    unavailable = StewardshipIdentityHealthWorker(
        store=store,
        stewardship=_stewardship(),
        directory=UnavailableDirectory(),
        interval_seconds=60,
    )

    assert await healthy.run_once() == "healthy"
    last_success = await store.read_state("stewardship_health:last_success")
    assert await unavailable.run_once() == "unavailable"

    assert await store.read_state("stewardship_health:last_success") == last_success
    current = await store.read_state("stewardship_health:current")
    assert current is not None and current["status"] == "unavailable"
    assert current["provider_error_type"] == "ConnectError"
    assert len(store.audit_entries) == 2


async def test_health_worker_reports_inactive_steward_without_failing_closed() -> None:
    stewardship = _stewardship()
    target = sorted(
        {
            *stewardship.maintainer_oids,
            *(
                subject.id
                for agent in stewardship.agents.values()
                for subject in agent.stewards
                if subject.kind.value == "user"
            ),
        }
    )[0]
    reduced = StaticHumanIdentityDirectory(
        identity for identity in _active_identities() if identity.subject_id != target
    )
    worker = StewardshipIdentityHealthWorker(
        store=(store := InMemoryStateStore()),
        stewardship=stewardship,
        directory=reduced,
        interval_seconds=60,
    )

    assert await worker.run_once() == "degraded"
    current = await store.read_state("stewardship_health:current")
    assert current is not None and current["findings"]


def test_health_builder_requires_complete_durable_prerequisites() -> None:
    with pytest.raises(RuntimeError, match="STATE_STORE_DSN"):
        build_stewardship_identity_health_worker(
            store=InMemoryStateStore(),
            http_client=None,
            identity=None,
            environment={"FDAI_STEWARDSHIP_AUDIT_INTERVAL_SECONDS": "60"},
            config_path=_CONFIG,
        )

    assert (
        build_stewardship_identity_health_worker(
            store=InMemoryStateStore(),
            http_client=None,
            identity=None,
            environment={},
            config_path=_CONFIG,
        )
        is None
    )
