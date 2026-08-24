"""Heimdall provider-schema drift ownership tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall
from fdai.agents.saga import Saga
from fdai.delivery.provider_schema import (
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    ProviderSchemaType,
)
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger
from fdai.delivery.provider_schema_watcher import (
    ProviderSchemaSourceBinding,
    ProviderSchemaSourceKind,
    ProviderSchemaWatcher,
)


class _Source:
    def __init__(self, snapshot: ProviderSchemaSnapshot) -> None:
        self._snapshot = snapshot

    async def collect(self) -> ProviderSchemaSnapshot:
        return self._snapshot


def _package() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "kind": "provider-schema-drift-review",
        "provider": "azure",
        "source_revision": "a" * 40,
        "baseline_digest": "sha256:" + "1" * 64,
        "observed_digest": "sha256:" + "2" * 64,
        "drift_digest": "3" * 64,
        "drift_kind": "breaking",
        "added_types": [],
        "removed_types": ["microsoft.example/old"],
        "added_stable_versions": [],
        "removed_stable_versions": [],
        "added_preview_versions": [],
        "removed_preview_versions": [],
        "type_count": 10,
        "modeled_count": 2,
        "coverage_status_counts": {"modeled": 2, "unsupported-with-reason": 8},
        "review_required": True,
        "grants_authority": False,
    }


async def test_heimdall_publishes_schema_review_through_owned_drift_topic() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus)

    published = await heimdall.publish_provider_schema_drift(_package())

    assert published is True
    message = bus.messages_on("object.drift")[-1]
    assert message.principal == "Heimdall"
    assert message.payload["event_type"] == "provider.schema_drift"
    assert message.payload["authority_ceiling"] == "shadow"
    assert message.payload["grants_authority"] is False
    assert heimdall.behavior_snapshot()["provider_schema_drift:breaking"] == 1


async def test_heimdall_validates_before_transport_and_holds_without_bus() -> None:
    heimdall = Heimdall()

    assert await heimdall.publish_provider_schema_drift(_package()) is False
    invalid = _package()
    invalid["grants_authority"] = True
    with pytest.raises(ProviderSchemaError, match="authority boundary"):
        await heimdall.publish_provider_schema_drift(invalid)


async def test_provider_schema_drift_reaches_hil_verdict_and_saga_audit() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus)
    forseti = Forseti(bus=bus)
    saga = Saga()
    saga.bind_bus(bus)
    bus.subscribe("object.drift", "Forseti", forseti.on_typed_message)
    bus.subscribe("object.verdict", "Saga", saga.on_typed_message)

    assert await heimdall.publish_provider_schema_drift(_package()) is True

    drift = bus.messages_on("object.drift")[-1].payload
    verdict = bus.messages_on("object.verdict")[-1].payload
    assert verdict["risk_verdict"] == "hil"
    assert verdict["reason"] == "no_rule_match"
    assert verdict["action_type"] == ""
    assert verdict["correlation_id"] == drift["correlation_id"]
    assert verdict["idempotency_key"] == drift["idempotency_key"]
    entries = saga.audit_chain.entries_for_correlation(str(drift["correlation_id"]))
    assert len(entries) == 1
    assert entries[0].principal == "Forseti"
    assert entries[0].topic == "object.verdict"


async def test_breaking_watcher_package_reaches_heimdall_owned_drift_topic(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    widget = ProviderSchemaType(
        resource_type="Microsoft.Example/widgets",
        stable_api_versions=("2025-01-01",),
        preview_api_versions=(),
        preferred_api_version="2025-01-01",
        source_document="generated/example/types.md",
    )
    report = ProviderSchemaType(
        resource_type="Microsoft.Example/reports",
        stable_api_versions=("2025-01-01",),
        preview_api_versions=(),
        preferred_api_version="2025-01-01",
        source_document="generated/example/types.md",
    )
    baseline = ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision="a" * 40,
        types=(widget, report),
    )
    observed = ProviderSchemaSnapshot.build(
        provider="azure",
        source_revision="b" * 40,
        types=(widget,),
    )
    ledger = ProviderSchemaLedger(tmp_path)
    ledger.record_snapshot(baseline, observed_at=now, accept_baseline=True)
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    heimdall = Heimdall(bus=bus)
    watcher = ProviderSchemaWatcher(
        provider="azure",
        sources=(
            ProviderSchemaSourceBinding(
                name="fixture",
                kind=ProviderSchemaSourceKind.OFFLINE,
                source=_Source(observed),
            ),
        ),
        ledger=ledger,
        modeled_provider_types=frozenset(),
        review_publisher=heimdall,
    )

    receipt = await watcher.run(now=now, force=True)

    assert receipt.review_dispatched is True
    assert receipt.review_handoff_reason is None
    assert ledger.read_baseline("azure") == baseline
    message = bus.messages_on("object.drift")[-1]
    assert message.principal == "Heimdall"
    assert message.payload["drift_digest"] == receipt.drift_digest
    assert message.payload["review_required"] is True
    assert message.payload["grants_authority"] is False
