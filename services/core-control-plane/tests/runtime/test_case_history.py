from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.core.case_history.dual_write import DualWriteCaseHistoryMetadataStore
from fdai.core.learning import NoImprovement, PostTurnReviewInput
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.runtime.case_history import (
    CaseHistoryRetentionTickPublisher,
    build_case_history_runtime,
    case_history_retention_days,
    case_history_retention_tick_seconds,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            audience=audience,
        )


class _Model:
    def __init__(self, identity: str, family: str) -> None:
        self._identity = identity
        self._family = family

    @property
    def model_identity(self) -> str:
        return self._identity

    @property
    def model_family(self) -> str:
        return self._family

    async def propose(self, review_input: PostTurnReviewInput):
        return NoImprovement(reason=f"no_change_{review_input.review_id}")


def test_case_history_runtime_is_disabled_without_container() -> None:
    assert (
        build_case_history_runtime(
            container_url=None,
            state_store=InMemoryStateStore(),
            identity=None,
            http_client=None,
        )
        is None
    )


async def test_case_history_runtime_builds_storage_and_mixed_family_analysis() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        runtime = build_case_history_runtime(
            container_url="https://example.blob.core.windows.net/case-history",
            state_store=InMemoryStateStore(),
            identity=_Identity(),
            http_client=client,
            models=(
                _Model("publisher-a:family-a:model-a", "family-a"),
                _Model("publisher-b:family-b:model-b", "family-b"),
            ),
        )
    assert runtime is not None
    assert runtime.analyzer is not None


async def test_case_history_runtime_uses_relational_metadata_when_dsn_is_configured() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        runtime = build_case_history_runtime(
            container_url="https://example.blob.core.windows.net/case-history",
            state_store=InMemoryStateStore(),
            identity=_Identity(),
            http_client=client,
            dsn="postgresql://example.invalid/fdai",
        )
    assert runtime is not None
    assert isinstance(runtime.metadata, DualWriteCaseHistoryMetadataStore)


def test_case_history_retention_defaults_and_validation() -> None:
    assert case_history_retention_days(None, None) == (30, 60)
    assert case_history_retention_days("7", "14") == (7, 14)
    with pytest.raises(ValueError, match="deletion days"):
        case_history_retention_days("30", "7")
    with pytest.raises(ValueError, match="positive integer"):
        case_history_retention_days("zero", "60")


async def test_retention_tick_publishes_bounded_raw_ingress_event() -> None:
    bus = InMemoryEventBus()
    now = datetime(2026, 7, 1, tzinfo=UTC)
    publisher = CaseHistoryRetentionTickPublisher(
        bus=bus,
        topic="raw.events",
        interval_seconds=60,
    )
    await publisher.publish_once(now=now)

    envelope = await anext(bus.subscribe("raw.events", "retention-test"))
    assert envelope.key == f"case-history-retention:{int(now.timestamp()) // 60}"
    assert envelope.payload["event_type"] == "case_history.retention_due"
    assert envelope.payload["attributes"] == {"as_of": now.isoformat()}


async def test_retention_tick_uses_latest_runtime_interval() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    settings = RuntimeSettingsService(store=store, env={})
    publisher = CaseHistoryRetentionTickPublisher(
        bus=bus,
        topic="raw.events",
        interval_seconds=60,
        runtime_settings=settings,
    )
    await settings.update(
        actor_id="owner-1",
        changes={"case_history.retention_tick_seconds": 300},
        expected_revision=0,
    )
    now = datetime(2026, 7, 1, tzinfo=UTC)

    await publisher.publish_once(now=now)

    envelope = await anext(bus.subscribe("raw.events", "retention-settings-test"))
    assert envelope.key == f"case-history-retention:{int(now.timestamp()) // 300}"


def test_case_history_retention_tick_interval_validation() -> None:
    assert case_history_retention_tick_seconds(None) == 86_400
    assert case_history_retention_tick_seconds("300") == 300
    with pytest.raises(ValueError, match="positive integer"):
        case_history_retention_tick_seconds("0")
