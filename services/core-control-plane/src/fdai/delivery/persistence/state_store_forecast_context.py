"""Read exact retained forecast context; independent admission remains a Core requirement."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fdai.core.detection.forecast_history import StateTransitionForecastHistoryCollector
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.forecast_context import (
    ForecastContextEvidence,
    ForecastContextRequest,
    ForecastContextUnavailableError,
)
from fdai.shared.providers.state_store import StateStore


def forecast_context_state_key(request: ForecastContextRequest) -> str:
    """Address one target's immutable history window independently of read time."""
    material = {
        "access_scope_digest": request.access_scope_digest,
        "target_digest": request.target_digest,
        "horizon_started_at": request.horizon_started_at.astimezone(UTC).isoformat(),
        "horizon_ended_at": request.horizon_ended_at.astimezone(UTC).isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"forecast-context-history:v1:{digest}"


class StateStoreForecastContextProvider:
    """Resolve retained history without interpreting missing state as absence of intervention."""

    def __init__(
        self,
        store: StateStore,
        *,
        admission: DecisionEvidenceAdmissionProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        collector: StateTransitionForecastHistoryCollector | None = None,
    ) -> None:
        self._store = store
        self._admission = admission
        self._clock = clock or (lambda: datetime.now(UTC))
        self._collector = collector

    async def ingest(self, payload: Mapping[str, Any]) -> str:
        """Verify four source coverage slices and retain one exact episode history.

        Huginn authenticates the transport owner; independent admissions authenticate source
        coverage and the resulting history. Empty records alone never prove completeness.
        """
        if (
            payload.get("producer_principal") != "Huginn"
            or payload.get("event_type") != "forecast.context_history.v1"
        ):
            raise PermissionError("forecast history requires normalized Huginn ingress")
        return await self._retain(payload)

    async def _retain(self, payload: Mapping[str, Any]) -> str:
        """Heimdall-owned persistence shared by authenticated ingress and source collection."""
        async with asyncio.timeout(5):
            attributes = payload.get("attributes")
            kinds = {"actions", "changes", "resource_lifecycle", "excluded_windows"}
            if not isinstance(attributes, dict) or set(attributes) != kinds:
                raise ValueError("forecast history requires every source coverage slice")
            if self._admission is None:
                raise ForecastContextUnavailableError(
                    "forecast history independent admission is unavailable"
                )
            sources = tuple(_parse_evidence(attributes[kind]) for kind in sorted(kinds))
            first = sources[0]
            scope = (
                first.access_scope_digest,
                first.target_digest,
                first.horizon_started_at,
                first.horizon_ended_at,
            )
            for source in sources:
                if (
                    source.access_scope_digest,
                    source.target_digest,
                    source.horizon_started_at,
                    source.horizon_ended_at,
                ) != scope:
                    raise ValueError("forecast history source target or window mismatch")
            evidence = ForecastContextEvidence(
                access_scope_digest=first.access_scope_digest,
                target_digest=first.target_digest,
                horizon_started_at=first.horizon_started_at,
                horizon_ended_at=first.horizon_ended_at,
                recorded_at=max(source.recorded_at for source in sources),
                valid_until=min(source.valid_until for source in sources),
                complete=all(source.complete for source in sources),
                source_revision=hashlib.sha256(
                    "".join(source.digest for source in sources).encode()
                ).hexdigest(),
                evidence_refs=tuple(
                    sorted({ref for source in sources for ref in source.evidence_refs})
                ),
                intervention_refs=tuple(
                    sorted({ref for source in sources for ref in source.intervention_refs})
                ),
                resource_deleted=any(source.resource_deleted for source in sources),
                excluded_window=any(source.excluded_window for source in sources),
            )
            request = ForecastContextRequest(*scope, as_of=self._clock())
            key = forecast_context_state_key(request)
            raw = asdict(evidence)
            for name in ("horizon_started_at", "horizon_ended_at", "recorded_at", "valid_until"):
                raw[name] = getattr(evidence, name).astimezone(UTC).isoformat()
            for name in ("evidence_refs", "intervention_refs"):
                raw[name] = sorted(raw[name])
            stored = await self._store.read_state(key)
            revision, history = _history(stored)
            if raw in history:
                return evidence.digest
            previous = _parse_evidence(history[-1]) if history else None
            if previous is not None:
                if (
                    payload.get("previous_context_digest") != previous.digest
                    or evidence.recorded_at <= previous.recorded_at
                ):
                    raise ValueError(
                        "forecast history amendment requires its exact current predecessor"
                    )
            elif payload.get("previous_context_digest") is not None:
                raise ValueError("forecast history predecessor is unavailable")
            if len(history) >= 32:
                raise ForecastContextUnavailableError(
                    "forecast history revision capacity exhausted"
                )
            deadlines = []
            for kind, source in zip(sorted(kinds), sources, strict=True):
                deadlines.append(
                    await self._require_admission(source, purpose=f"forecast-history-{kind}")
                )
            deadlines.append(await self._require_admission(evidence, purpose="forecast-context"))
            if self._clock() >= min(deadlines):
                raise ForecastContextUnavailableError(
                    "forecast history admission expired during verification"
                )
            value = {"revision": len(history) + 1, "history": [*history, raw]}
            audit = {
                "action_kind": "forecast.context_history_retained",
                "owner_agent": "Heimdall",
                "idempotency_key": evidence.digest,
                "evidence_digest": evidence.digest,
                "previous_context_digest": previous.digest if previous is not None else None,
                "scope_digest": evidence.access_scope_digest,
                "timestamp": self._clock().isoformat(),
                "execution_authority": False,
                "promotion_authority": False,
            }
            if stored is None:
                created = await self._store.write_state_with_audit_if_absent(key, value, audit)
            else:
                created = await self._store.compare_and_set_state_with_audit(
                    key,
                    value,
                    expected_revision=revision,
                    audit_entry=audit,
                )
            if not created and raw not in _history(await self._store.read_state(key))[1]:
                raise ValueError("forecast history concurrent revision conflict")
            return evidence.digest

    async def _require_admission(
        self, evidence: ForecastContextEvidence, *, purpose: str
    ) -> datetime:
        if self._admission is None:
            raise ForecastContextUnavailableError("forecast history admission is unavailable")
        receipt = await self._admission.admit(
            evidence_digest="sha256:" + evidence.digest,
            scope_digest="sha256:" + evidence.access_scope_digest,
            purpose_id=purpose,
            source_revision=evidence.source_revision,
        )
        now = self._clock()
        if not isinstance(receipt, DecisionEvidenceAdmission) or (
            not evidence.recorded_at
            <= receipt.verified_at
            <= now
            < min(receipt.valid_until, evidence.valid_until)
            or assess_decision_evidence_admission(
                receipt,
                expected_evidence_digest="sha256:" + evidence.digest,
                expected_scope_digest="sha256:" + evidence.access_scope_digest,
                expected_purpose_id=purpose,
                expected_source_revision=evidence.source_revision,
                evaluated_at=now,
            )
        ):
            raise ForecastContextUnavailableError(
                "forecast history source coverage admission failed"
            )
        return min(receipt.valid_until, evidence.valid_until)

    async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence:
        raw = await self._store.read_state(forecast_context_state_key(request))
        _revision, history = _history(raw)
        if self._collector is not None and (
            not history
            or request.as_of >= _parse_evidence(history[-1]).valid_until
            or not _parse_evidence(history[-1]).complete
        ):
            async with asyncio.timeout(5):
                attributes = await self._collector.collect(request)
                await self._retain(
                    {
                        "attributes": attributes,
                        "previous_context_digest": _parse_evidence(history[-1]).digest
                        if history
                        else None,
                    }
                )
                _revision, history = _history(
                    await self._store.read_state(forecast_context_state_key(request))
                )
        evidence = _parse_evidence(history[-1] if history else None)
        if (
            evidence.access_scope_digest != request.access_scope_digest
            or evidence.target_digest != request.target_digest
            or evidence.horizon_started_at != request.horizon_started_at
            or evidence.horizon_ended_at != request.horizon_ended_at
            or not evidence.recorded_at <= request.as_of < evidence.valid_until
        ):
            raise ForecastContextUnavailableError(
                "forecast context history does not match the request"
            )
        return evidence


def _history(raw: Any) -> tuple[int, list[dict[str, Any]]]:
    """Read a bounded revision envelope or retain a legacy flat record during upgrade."""
    if raw is None:
        return 0, []
    if isinstance(raw, dict) and set(raw) == {"revision", "history"}:
        revision, history = raw["revision"], raw["history"]
        if (
            type(revision) is not int
            or not isinstance(history, list)
            or not 1 <= len(history) <= 32
            or revision != len(history)
        ):
            raise ForecastContextUnavailableError("forecast history revision envelope is invalid")
        previous = None
        for item in history:
            evidence = _parse_evidence(item)
            if previous is not None and (
                evidence.recorded_at <= previous.recorded_at
                or (
                    evidence.access_scope_digest,
                    evidence.target_digest,
                    evidence.horizon_started_at,
                    evidence.horizon_ended_at,
                )
                != (
                    previous.access_scope_digest,
                    previous.target_digest,
                    previous.horizon_started_at,
                    previous.horizon_ended_at,
                )
            ):
                raise ForecastContextUnavailableError("forecast history revision chain is invalid")
            previous = evidence
        return revision, history
    _parse_evidence(raw)
    return 0, [dict(raw)]


def _parse_evidence(raw: Any) -> ForecastContextEvidence:
    """Parse the bounded source and retained result through the same strict contract."""
    fields = {
        "access_scope_digest",
        "target_digest",
        "horizon_started_at",
        "horizon_ended_at",
        "recorded_at",
        "valid_until",
        "complete",
        "source_revision",
        "evidence_refs",
        "intervention_refs",
        "resource_deleted",
        "excluded_window",
    }
    if not isinstance(raw, Mapping) or set(raw) != fields:
        raise ForecastContextUnavailableError("forecast context history is missing or malformed")
    values: dict[str, Any] = dict(raw)
    try:
        for name in ("horizon_started_at", "horizon_ended_at", "recorded_at", "valid_until"):
            value = values[name]
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError("invalid context timestamp")
            values[name] = datetime.fromisoformat(value)
        for name in ("evidence_refs", "intervention_refs"):
            value = values[name]
            if not isinstance(value, (list, tuple)) or len(value) > 64:
                raise ValueError("invalid context references")
            values[name] = tuple(value)
        return ForecastContextEvidence(**values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ForecastContextUnavailableError("forecast context history is invalid") from exc
