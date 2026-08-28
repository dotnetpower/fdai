from __future__ import annotations

import asyncio
import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostCollectionCursor,
    CostCollectionRequest,
    CostObservation,
    CostObservationPage,
    CostPackageActivation,
    SignedCostEffectEstimate,
)

from fdai_cost_governance import (
    AzureFocusObservationAdapter,
    CostAnalyzerService,
    CostCollectorService,
    CostHttpResponse,
    CostJobConfig,
    RollingCostAdvisoryProvider,
)

_NOW = datetime(2028, 1, 2, tzinfo=UTC)
_RELEASE_ID = "ontology-release:2028-01"
_RELEASE = "sha256:" + "3" * 64
_SCOPE = "subscriptions/00000000-0000-0000-0000-000000000000"


def _activation(
    *,
    available: bool = True,
    enabled: bool = True,
    revision: int = 1,
) -> CostPackageActivation:
    return CostPackageActivation(
        vertical_id="cost-governance",
        package_id="cost-governance",
        available=available,
        enabled=enabled and available,
        availability_reasons=(() if available else ("missing_provider:cost-estimator",)),
        package_version="0.1.0",
        image_digest=f"sha256:{'b' * 64}",
        asset_manifest_digest=f"sha256:{'c' * 64}",
        semantic_profile_digest=f"sha256:{'d' * 64}",
        revision=revision,
        effective_at=_NOW,
        ontology_release_id=_RELEASE_ID,
        ontology_release_digest=_RELEASE,
        source_authority="vertical-package-activation-store",
        previously_enabled=not enabled,
    )


def _observation(
    *,
    suffix: str = "1",
    service_id: str = "service-a",
    completeness: Decimal = Decimal("1"),
    observed_at: datetime = _NOW,
) -> CostObservation:
    return CostObservation(
        observation_id=f"costobs:{suffix * 64}",
        package_id="cost-governance",
        scope_id=_SCOPE,
        service_id=service_id,
        amount=Decimal("100"),
        currency="USD",
        event_start_at=observed_at - timedelta(hours=2),
        event_end_at=observed_at - timedelta(hours=1),
        observed_at=observed_at,
        recorded_at=observed_at,
        source_authority="azure-cost-management-focus",
        source_uri="/subscriptions/example/resources/resource-a",
        completeness=completeness,
        ontology_release_id=_RELEASE_ID,
        ontology_release_digest=_RELEASE,
        evidence_digest="sha256:" + suffix * 64,
        retention_until=observed_at + timedelta(days=30),
    )


def test_activation_keeps_availability_independent_and_fail_closed() -> None:
    available_disabled = _activation(available=True, enabled=False)
    assert available_disabled.available is True
    assert available_disabled.enabled is False
    assert available_disabled.availability_reasons == ()

    with pytest.raises(ValueError, match="unavailable package"):
        replace(
            available_disabled,
            available=False,
            availability_reasons=("missing_provider:cost-estimator",),
            enabled=True,
        )


class Activation:
    def __init__(self, snapshots: list[CostPackageActivation | None]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    async def read_cost_activation(self, package_id: str) -> CostPackageActivation | None:
        assert package_id == "cost-governance"
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


class Provider:
    def __init__(self, page: CostObservationPage) -> None:
        self.page = page
        self.calls = 0

    async def collect_cost_page(self, request, *, resume_token):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.page


class Store:
    def __init__(self, observations: tuple[CostObservation, ...] = ()) -> None:
        self.observations = list(observations)
        self.cursor: CostCollectionCursor | None = None
        self.reads = 0
        self.appends = 0

    async def read_cost_cursor(self, package_id: str, scope_id: str):
        return self.cursor

    async def append_cost_page(
        self,
        page,
        *,
        package_id,
        scope_id,
        expected_revision,
        coverage_through_at,
        retention_floor_at,
    ):  # type: ignore[no-untyped-def]
        if self.cursor is not None and self.cursor.revision != expected_revision:
            return False
        if self.cursor is None and expected_revision != 0:
            return False
        known = {item.observation_id for item in self.observations}
        self.observations.extend(
            item for item in page.observations if item.observation_id not in known
        )
        previous = self.cursor
        self.cursor = CostCollectionCursor(
            package_id=package_id,
            scope_id=scope_id,
            revision=expected_revision + 1,
            resume_token=page.next_resume_token,
            coverage_through_at=coverage_through_at,
            retention_floor_at=retention_floor_at,
            analysis_revision=previous.analysis_revision if previous else 0,
            last_published_at=previous.last_published_at if previous else None,
            last_published_observation_id=(
                previous.last_published_observation_id if previous else None
            ),
        )
        self.appends += 1
        return True

    async def read_cost_observations(
        self,
        *,
        package_id,
        scope_id,
        since,
        limit,
    ):  # type: ignore[no-untyped-def]
        self.reads += 1
        return tuple(item for item in self.observations if item.observed_at >= since)[:limit]

    async def advance_cost_analysis_cursor(
        self,
        *,
        package_id,
        scope_id,
        observation_id,
        observed_at,
        expected_analysis_revision,
    ):  # type: ignore[no-untyped-def]
        if self.cursor is None or self.cursor.analysis_revision != expected_analysis_revision:
            return False
        self.cursor = replace(
            self.cursor,
            analysis_revision=expected_analysis_revision + 1,
            last_published_at=observed_at,
            last_published_observation_id=observation_id,
        )
        return True


class Publisher:
    def __init__(self) -> None:
        self.items: list[tuple[str, int]] = []

    async def publish_cost_sample(self, observation, *, activation_revision):  # type: ignore[no-untyped-def]
        self.items.append((observation.observation_id, activation_revision))


def _config(**changes: object) -> CostJobConfig:
    values = {
        "package_id": "cost-governance",
        "ontology_release_id": _RELEASE_ID,
        "ontology_release_digest": _RELEASE,
        "known_service_ids": frozenset({"service-a"}),
    }
    values.update(changes)
    return CostJobConfig(**values)  # type: ignore[arg-type]


def _page(*items: CostObservation, complete: bool = True) -> CostObservationPage:
    return CostObservationPage(
        observations=items,
        next_resume_token=None if complete else "next",
        complete=complete,
        source_authority="azure-cost-management-focus",
        bytes_read=100,
        collected_at=_NOW,
    )


@pytest.mark.parametrize(
    ("available", "enabled"),
    [(True, False), (False, False)],
)
def test_inactive_jobs_make_zero_provider_store_or_publish_calls(
    available: bool,
    enabled: bool,
) -> None:
    activation = Activation([_activation(available=available, enabled=enabled)])
    provider = Provider(_page(_observation()))
    store = Store((_observation(),))
    publisher = Publisher()

    collected = asyncio.run(
        CostCollectorService(
            config=_config(),
            activation=activation,
            provider=provider,
            store=store,
            clock=lambda: _NOW,
        ).collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=1),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    analyzed = asyncio.run(
        CostAnalyzerService(
            config=_config(),
            activation=activation,
            store=store,
            publisher=publisher,
            clock=lambda: _NOW,
        ).analyze(scope_id=_SCOPE, since=_NOW - timedelta(days=1))
    )

    assert collected.status == analyzed.status == "disabled"
    assert provider.calls == store.appends == store.reads == 0
    assert publisher.items == []


def test_disable_between_read_and_append_leaves_store_unchanged() -> None:
    activation = Activation([_activation(), _activation(), _activation(enabled=False, revision=2)])
    provider = Provider(_page(_observation()))
    store = Store()
    result = asyncio.run(
        CostCollectorService(
            config=_config(),
            activation=activation,
            provider=provider,
            store=store,
            clock=lambda: _NOW,
        ).collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=1),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    assert result.status == "disabled"
    assert provider.calls == 1
    assert store.appends == 0


@pytest.mark.parametrize(
    ("item", "status"),
    [
        (_observation(service_id="unknown"), "unknown_service"),
        (_observation(completeness=Decimal("0.5")), "incomplete"),
        (_observation(observed_at=_NOW - timedelta(days=3)), "stale"),
    ],
)
def test_collector_rejects_unusable_evidence(item: CostObservation, status: str) -> None:
    provider = Provider(_page(item))
    store = Store()
    result = asyncio.run(
        CostCollectorService(
            config=_config(),
            activation=Activation([_activation()]),
            provider=provider,
            store=store,
            clock=lambda: _NOW,
        ).collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=4),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    assert result.status == status
    assert store.appends == 0


def test_cursor_cas_deduplicates_and_analyzer_restart_does_not_republish() -> None:
    item = _observation()
    store = Store()
    collector = CostCollectorService(
        config=_config(),
        activation=Activation([_activation()]),
        provider=Provider(_page(item)),
        store=store,
        clock=lambda: _NOW,
    )
    first = asyncio.run(
        collector.collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=1),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    publisher = Publisher()
    analyzer = CostAnalyzerService(
        config=_config(),
        activation=Activation([_activation()]),
        store=store,
        publisher=publisher,
        clock=lambda: _NOW,
    )
    one = asyncio.run(analyzer.analyze(scope_id=_SCOPE, since=_NOW - timedelta(days=1)))
    two = asyncio.run(analyzer.analyze(scope_id=_SCOPE, since=_NOW - timedelta(days=1)))

    assert first.status == one.status == two.status == "complete"
    assert store.cursor is not None and store.cursor.analysis_revision == 1
    assert publisher.items == [(item.observation_id, 1)]


def test_collector_stops_at_page_and_deadline_budgets() -> None:
    provider = Provider(_page(_observation(), complete=False))
    page_limited = asyncio.run(
        CostCollectorService(
            config=_config(max_pages=1),
            activation=Activation([_activation()]),
            provider=provider,
            store=Store(),
            clock=lambda: _NOW,
        ).collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=1),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    ticks = iter((_NOW, _NOW + timedelta(seconds=2)))
    deadline = asyncio.run(
        CostCollectorService(
            config=_config(attempt_timeout=timedelta(seconds=1)),
            activation=Activation([_activation()]),
            provider=Provider(_page(_observation())),
            store=Store(),
            clock=lambda: next(ticks),
        ).collect(
            scope_id=_SCOPE,
            start_at=_NOW - timedelta(days=1),
            end_at=_NOW - timedelta(seconds=1),
        )
    )
    assert page_limited.status == "page_limit"
    assert deadline.status == "deadline" and deadline.provider_calls == 0


def test_rolling_advisory_rejects_duplicate_reordered_and_invalid_facts() -> None:
    provider = RollingCostAdvisoryProvider(
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )

    def sample(index: int, amount: str = "100") -> CostAnalysisSample:
        return CostAnalysisSample(
            scope_id="scope-a",
            resource_id="resource-a",
            amount_usd=Decimal(amount),
            correlation_id=f"sample-{index}",
            observed_at=_NOW - timedelta(minutes=10 - index),
            source_authority="azure-cost-management-focus",
            completeness=Decimal("1"),
            ontology_release_digest=_RELEASE,
        )

    for index in range(3):
        assert asyncio.run(provider.analyze_cost_sample(sample(index))) is None
    finding = asyncio.run(provider.analyze_cost_sample(sample(3, "200")))
    assert finding is not None and finding.recommendation == "scale_down"
    assert asyncio.run(provider.analyze_cost_sample(sample(3, "200"))) is None
    reordered = replace(sample(99), observed_at=_NOW - timedelta(minutes=20))
    assert asyncio.run(provider.analyze_cost_sample(reordered)) is None
    stale = replace(sample(4), observed_at=_NOW - timedelta(days=3))
    assert asyncio.run(provider.analyze_cost_sample(stale)) is None
    assert provider.diagnostics == {
        "accepted": 4,
        "duplicate": 1,
        "reordered": 1,
        "stale": 1,
    }


def test_signed_estimates_are_advisory_and_do_not_change_spend_risk_contract() -> None:
    provider = RollingCostAdvisoryProvider(
        ontology_release_digest=_RELEASE,
        clock=lambda: _NOW,
    )
    estimate = provider.estimate_cost_effect("remediate.resize_vm_down")
    assert estimate is not None and estimate.monthly_delta_usd == Decimal("-25")
    assert {field.name for field in fields(SignedCostEffectEstimate)}.isdisjoint(
        {"approved", "execute", "executor", "promoted", "promotion"}
    )
    with pytest.raises(ValueError, match="source_authority"):
        replace(_observation(), source_authority="")


class Credential:
    def __init__(self) -> None:
        self.calls = 0

    async def access_token(self, *, deadline_at: datetime) -> str:
        self.calls += 1
        return "redacted-test-token"


class Transport:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = body
        self.calls = 0

    async def get(self, url, *, headers, max_bytes, deadline_at):  # type: ignore[no-untyped-def]
        self.calls += 1
        assert url.startswith("https://management.azure.com/")
        assert headers["Authorization"].startswith("Bearer ")
        return CostHttpResponse(200, json.dumps(self.body).encode())


def test_azure_focus_adapter_uses_injected_read_boundaries() -> None:
    body: dict[str, object] = {
        "collectedAt": _NOW.isoformat(),
        "properties": {
            "rows": [
                {
                    "serviceId": "service-a",
                    "billedCost": "12.5",
                    "billingCurrency": "USD",
                    "chargePeriodStart": (_NOW - timedelta(hours=2)).isoformat(),
                    "chargePeriodEnd": (_NOW - timedelta(hours=1)).isoformat(),
                    "sourceUri": "/subscriptions/example/resources/a",
                }
            ]
        },
    }
    credential = Credential()
    transport = Transport(body)
    adapter = AzureFocusObservationAdapter(
        transport=transport,
        credential=credential,
        ontology_release_id=_RELEASE_ID,
        ontology_release_digest=_RELEASE,
    )
    page = asyncio.run(
        adapter.collect_cost_page(
            CostCollectionRequest(
                package_id="cost-governance",
                scope_id=_SCOPE,
                start_at=_NOW - timedelta(days=1),
                end_at=_NOW - timedelta(seconds=1),
                page_size=10,
                deadline_at=_NOW + timedelta(minutes=1),
            ),
            resume_token=None,
        )
    )
    assert credential.calls == transport.calls == 1
    assert len(page.observations) == 1
    assert page.observations[0].amount == Decimal("12.5")
