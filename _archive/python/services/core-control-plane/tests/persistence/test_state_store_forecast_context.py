from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.persistence.state_store_forecast_context import (
    StateStoreForecastContextProvider,
    forecast_context_state_key,
)
from fdai.shared.providers.forecast_context import (
    ForecastContextEvidence,
    ForecastContextRequest,
    ForecastContextUnavailableError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def test_history_binding_canonicalizes_states_and_rejects_duplicate_active_states():
    from fdai.core.detection.forecast_history import ForecastHistoryBinding

    values = dict(
        kind="resource_lifecycle",
        access_scope_digest="a" * 64,
        target_ref="resource-example",
        state_type="resource_lifecycle",
        to_states=("inactive", "active"),
        active_states=("active",),
        source_identity="source-example",
        source_revision="revision-example",
        freshness_seconds=300,
    )
    assert ForecastHistoryBinding(**values).to_states == ("active", "inactive")
    for active_states in (
        ("active", "active"),
        ("active",) * 33,
        ("other",),
        ("active", "inactive"),
    ):
        with pytest.raises(ValueError):
            ForecastHistoryBinding(**{**values, "active_states": active_states})


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "partial",
        "empty",
        "wrong-source",
        "synthetic",
        "stale",
        "unknown-initial",
        "row-target",
        "row-type",
        "row-source",
        "row-revision",
        "row-synthetic",
        "nonboolean-synthetic",
        "row-conflict",
        "incomplete-row",
        "future-row",
        "old-row",
        "unknown-state",
        "duplicate-row",
        "broken-chain",
        "simultaneous",
        "truncated",
    ],
)
@pytest.mark.parametrize("active_before", [True, False])
@pytest.mark.parametrize("at_boundary", [True, False])
async def test_automatic_history_collection_requires_positive_exact_source_coverage(
    failure, active_before, at_boundary
):
    import hashlib

    from fdai.core.detection.forecast_history import (
        ForecastHistoryBinding,
        StateTransitionForecastHistoryCollector,
    )
    from fdai.core.ontology_platform.state_transitions import (
        OperationalStateTransition,
        StateTransitionAuthority,
        StateTransitionCoverage,
        StateTransitionLane,
        StateTransitionRead,
    )

    bindings = tuple(
        ForecastHistoryBinding(
            kind=kind,
            access_scope_digest="a" * 64,
            target_ref="resource-example",
            state_type=kind,
            to_states=("active", "inactive"),
            active_states=("active",) if kind in {"resource_lifecycle", "excluded_windows"} else (),
            source_identity="source-example",
            source_revision="revision-example",
            freshness_seconds=300,
        )
        for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows")
    )

    class _Source:
        calls = 0

        async def read(self, **query):
            self.calls += 1
            assert query["limit"] == 64 and query["subject_refs"] == ("resource-example",)
            assert query["to_states"] is None
            coverage = StateTransitionCoverage.create(
                subject_ref="resource-example",
                state_type=query["state_types"][0],
                coverage_start_at=query["start_at"],
                coverage_end_at=NOW,
                recorded_at=NOW,
                source_identity="other" if failure == "wrong-source" else "source-example",
                source_revision="revision-example",
                watermark="checkpoint-one",
                evidence_ref="coverage:example",
                complete=failure != "partial",
                limitation="partial" if failure == "partial" else None,
                synthetic=failure == "synthetic",
            )
            transitions = ()
            if (
                query["state_types"][0] in {"resource_lifecycle", "excluded_windows"}
                and failure != "unknown-initial"
            ):
                transitions = (
                    OperationalStateTransition.create(
                        idempotency_key=query["state_types"][0],
                        subject_ref="resource-example",
                        subject_type="Resource",
                        state_type=query["state_types"][0],
                        from_state="inactive" if active_before else "active",
                        to_state="active" if active_before else "inactive",
                        lane=StateTransitionLane.OBSERVED,
                        authority=StateTransitionAuthority.PROVIDER,
                        effective_at=NOW - timedelta(hours=1 if at_boundary else 2),
                        evidence_cutoff=NOW,
                        recorded_at=NOW,
                        source_identity="source-example",
                        source_revision="revision-example",
                        producer_id="observer-example",
                        producer_version="1.0.0",
                        freshness_ceiling_seconds=300,
                        completeness_basis_points=10_000,
                        evidence_refs=("event:example",),
                    ),
                )
            if transitions:
                changes = {
                    "row-target": {"subject_ref": "other-resource"},
                    "row-type": {"state_type": "other-state"},
                    "row-source": {"source_identity": "other-source"},
                    "row-revision": {"source_revision": "other-revision"},
                    "row-synthetic": {"synthetic": True},
                    "nonboolean-synthetic": {"synthetic": 0},
                    "row-conflict": {"conflicts": ("conflict:example",)},
                    "incomplete-row": {"completeness_basis_points": 9999},
                    "future-row": {"recorded_at": NOW + timedelta(seconds=1)},
                    "old-row": {"effective_at": query["start_at"] - timedelta(seconds=1)},
                    "unknown-state": {"to_state": "unreviewed"},
                }
                fields = asdict(transitions[0])
                fields.pop("transition_id")
                if failure in changes:
                    transitions = (
                        OperationalStateTransition.create(**{**fields, **changes[failure]}),
                    )
                elif failure == "duplicate-row":
                    transitions *= 2
                elif failure == "truncated":
                    transitions *= 65
                elif failure in {"broken-chain", "simultaneous"}:
                    fields["idempotency_key"] += ":second"
                    if failure == "broken-chain":
                        fields["effective_at"] += timedelta(seconds=1)
                    transitions += (OperationalStateTransition.create(**fields),)
            return StateTransitionRead(
                transitions=transitions,
                coverage=() if failure == "empty" else (coverage,),
                complete=failure != "partial",
                limitation="partial" if failure == "partial" else None,
            )

    source = _Source()
    collector = StateTransitionForecastHistoryCollector(store=source, bindings=bindings)
    request = replace(
        _request(),
        target_digest=hashlib.sha256(b"resource-example").hexdigest(),
        as_of=NOW + timedelta(minutes=5) if failure == "stale" else NOW,
    )
    if failure:
        with pytest.raises(ForecastContextUnavailableError):
            await collector.collect(request)
    else:
        result = await collector.collect(request)
        assert source.calls == 4 and len(result) == 4
        assert all(item["complete"] and not item["intervention_refs"] for item in result.values())
        assert result["excluded_windows"]["excluded_window"] is active_before
        assert result["resource_lifecycle"]["resource_deleted"] is active_before
        from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

        class _Admission:
            async def admit(self, **values):
                return DecisionEvidenceAdmission(
                    **values,
                    receipt_digest="sha256:" + "d" * 64,
                    verification_bundle_digest="sha256:" + "e" * 64,
                    verified_at=NOW,
                    valid_until=NOW + timedelta(minutes=5),
                )

        retained = InMemoryStateStore()
        provider = StateStoreForecastContextProvider(
            retained, admission=_Admission(), collector=collector, clock=lambda: NOW
        )
        current = await provider.read(request)
        assert current.complete
        assert source.calls == 8
        assert await provider.read(request) == current
        assert source.calls == 8
        assert await StateStoreForecastContextProvider(retained).read(request) == current
        assert await retained.verify_chain()


def _request() -> ForecastContextRequest:
    return ForecastContextRequest(
        access_scope_digest="a" * 64,
        target_digest="b" * 64,
        horizon_started_at=NOW - timedelta(hours=1),
        horizon_ended_at=NOW,
        as_of=NOW,
    )


def _record() -> dict[str, object]:
    request = _request()
    evidence = ForecastContextEvidence(
        access_scope_digest=request.access_scope_digest,
        target_digest=request.target_digest,
        horizon_started_at=request.horizon_started_at,
        horizon_ended_at=request.horizon_ended_at,
        recorded_at=NOW,
        valid_until=NOW + timedelta(minutes=5),
        complete=True,
        source_revision="c" * 64,
        evidence_refs=("context-history:example",),
    )
    record = asdict(evidence)
    for key in ("horizon_started_at", "horizon_ended_at", "recorded_at", "valid_until"):
        record[key] = record[key].isoformat()
    return record


async def test_missing_history_is_unknown_not_a_complete_empty_result() -> None:
    with pytest.raises(ForecastContextUnavailableError, match="missing"):
        await StateStoreForecastContextProvider(InMemoryStateStore()).read(_request())


async def test_exact_retained_history_survives_provider_restart() -> None:
    store = InMemoryStateStore()
    await store.write_state(forecast_context_state_key(_request()), _record())
    first = await StateStoreForecastContextProvider(store).read(_request())
    second = await StateStoreForecastContextProvider(store).read(_request())
    assert first == second
    assert first.complete is True
    assert first.intervention_refs == ()


@pytest.mark.parametrize(
    "change",
    [
        {"target_digest": "d" * 64},
        {"complete": "true"},
        {"execution_authority": True},
        {"evidence_refs": []},
        {"valid_until": NOW.isoformat()},
        {"recorded_at": "2026-09-14"},
    ],
)
async def test_untrusted_or_mismatched_record_cannot_be_read(change: dict[str, object]) -> None:
    store = InMemoryStateStore()
    await store.write_state(forecast_context_state_key(_request()), {**_record(), **change})
    with pytest.raises(ForecastContextUnavailableError):
        await StateStoreForecastContextProvider(store).read(_request())


def test_context_address_is_scope_and_window_bound_but_not_read_time() -> None:
    request = _request()
    assert forecast_context_state_key(request) == forecast_context_state_key(
        replace(request, as_of=NOW + timedelta(seconds=1))
    )
    assert forecast_context_state_key(request) != forecast_context_state_key(
        replace(request, access_scope_digest="e" * 64)
    )


@pytest.mark.parametrize("change", [{"recorded_at": 0}, {"intervention_refs": "invalid"}])
async def test_untyped_record_fields_are_unavailable(change: dict[str, object]) -> None:
    store = InMemoryStateStore()
    await store.write_state(forecast_context_state_key(_request()), {**_record(), **change})
    with pytest.raises(ForecastContextUnavailableError):
        await StateStoreForecastContextProvider(store).read(_request())


async def test_history_ingress_builds_retained_context_from_verified_sources() -> None:
    from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

    class _Admission:
        async def admit(self, **values):
            return DecisionEvidenceAdmission(
                **values,
                receipt_digest="sha256:" + "d" * 64,
                verification_bundle_digest="sha256:" + "e" * 64,
                verified_at=NOW,
                valid_until=NOW + timedelta(minutes=5),
            )

    store = InMemoryStateStore()
    provider = StateStoreForecastContextProvider(store, admission=_Admission(), clock=lambda: NOW)
    payload = {
        "producer_principal": "Huginn",
        "event_type": "forecast.context_history.v1",
        "attributes": {
            kind: _record()
            for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows")
        },
    }
    digest = await provider.ingest(payload)
    assert await provider.ingest(payload) == digest
    result = await StateStoreForecastContextProvider(store).read(_request())
    assert result.complete and result.digest == digest
    from fdai.core.detection.forecast_context import _context_ref

    assert _context_ref(result) == "forecast-context:" + digest
    assert await store.verify_chain()
    payload["attributes"].pop("actions")
    with pytest.raises(ValueError, match="every source"):
        await provider.ingest(payload)


@pytest.mark.parametrize("legacy", [False, True])
async def test_history_amendment_keeps_prior_evidence_and_never_replays_it_as_current(legacy):
    await exercise_history_amendment(InMemoryStateStore(), legacy=legacy)


async def exercise_history_amendment(store, *, legacy):
    """Exercise the same first-write and amendment contract on fake and PostgreSQL stores."""
    from copy import deepcopy

    from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

    instant = NOW

    class _Admission:
        async def admit(self, **values):
            return DecisionEvidenceAdmission(
                **values,
                receipt_digest="sha256:" + "d" * 64,
                verification_bundle_digest="sha256:" + "e" * 64,
                verified_at=instant,
                valid_until=instant + timedelta(minutes=5),
            )

    provider = StateStoreForecastContextProvider(
        store, admission=_Admission(), clock=lambda: instant
    )
    original = {
        "producer_principal": "Huginn",
        "event_type": "forecast.context_history.v1",
        "attributes": {
            kind: _record()
            for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows")
        },
    }
    first_digest = await provider.ingest(original)
    if legacy:
        retained = await store.read_state(forecast_context_state_key(_request()))
        await store.write_state(forecast_context_state_key(_request()), retained["history"][0])
    instant += timedelta(minutes=6)
    changed = deepcopy(original)
    for source in changed["attributes"].values():
        source["recorded_at"] = instant.isoformat()
        source["valid_until"] = (instant + timedelta(minutes=5)).isoformat()
    changed["attributes"]["actions"]["intervention_refs"] = ["action:newly-recorded"]
    with pytest.raises(ValueError, match="predecessor"):
        await provider.ingest(changed)
    changed["previous_context_digest"] = first_digest
    second_digest = await provider.ingest(changed)
    assert second_digest != first_digest
    assert await provider.ingest(original) == first_digest
    current = await provider.read(replace(_request(), as_of=instant))
    assert current.digest == second_digest and current.intervention_refs == (
        "action:newly-recorded",
    )
    retained = await store.read_state(forecast_context_state_key(_request()))
    assert retained["revision"] == 2 and len(retained["history"]) == 2
    assert await store.verify_chain()


@pytest.mark.parametrize(
    "failure", ["owner", "unbound", "scope", "missing-predecessor", "admission", "conflict"]
)
async def test_history_ingress_rejects_untrusted_or_conflicting_coverage(failure):
    from unittest.mock import AsyncMock

    from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission

    class _Admission:
        async def admit(self, **values):
            if failure == "admission":
                return None
            return DecisionEvidenceAdmission(
                **values,
                receipt_digest="sha256:" + "d" * 64,
                verification_bundle_digest="sha256:" + "e" * 64,
                verified_at=NOW,
                valid_until=NOW + timedelta(minutes=5),
            )

    store = InMemoryStateStore()
    if failure == "conflict":
        store.write_state_with_audit_if_absent = AsyncMock(return_value=False)
    provider = StateStoreForecastContextProvider(
        store, admission=None if failure == "unbound" else _Admission(), clock=lambda: NOW
    )
    payload = {
        "producer_principal": "Huginn",
        "event_type": "forecast.context_history.v1",
        "attributes": {
            kind: _record()
            for kind in ("actions", "changes", "resource_lifecycle", "excluded_windows")
        },
    }
    if failure == "owner":
        payload["producer_principal"] = "Mimir"
    elif failure == "scope":
        payload["attributes"]["actions"]["target_digest"] = "f" * 64
    elif failure == "missing-predecessor":
        payload["previous_context_digest"] = "d" * 64
    with pytest.raises((PermissionError, ValueError, ForecastContextUnavailableError)):
        await provider.ingest(payload)
    assert await store.read_state(forecast_context_state_key(_request())) is None


@pytest.mark.parametrize(
    "failure",
    ["revision-boolean", "revision-count", "history-empty", "reverse-time", "changed-scope"],
)
async def test_retained_history_chain_corruption_never_returns_current_evidence(failure):
    first = _record()
    second = {**first, "recorded_at": (NOW + timedelta(seconds=1)).isoformat()}
    value = {"revision": 2, "history": [first, second]}
    if failure == "revision-boolean":
        value["revision"] = True
    elif failure == "revision-count":
        value["revision"] = 1
    elif failure == "history-empty":
        value = {"revision": 0, "history": []}
    elif failure == "reverse-time":
        value["history"] = [second, first]
    else:
        second["access_scope_digest"] = "f" * 64
    store = InMemoryStateStore()
    await store.write_state(forecast_context_state_key(_request()), value)
    with pytest.raises(ForecastContextUnavailableError):
        await StateStoreForecastContextProvider(store).read(_request())
