"""Durable trusted-evidence source and content-free request outbox for Assurance Twin."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from fdai.core.assurance_twin.report import build_posture_assessment_report
from fdai.delivery.assurance_twin_evidence_clock import (
    AssuranceTwinEvidenceClockCapacityError,
    AssuranceTwinEvidenceClockContentionError,
    AssuranceTwinEvidenceExpiredError,
    StateStoreTwinEvidenceClock,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    advance_target_outbox as _advance_target_outbox,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    decode_evidence as _decode,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    evidence_identity as _evidence_identity,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    rule_assessment_body,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    valid_digest as _digest,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    validate_common as _validate_common,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    validate_findings as _validate_findings,
)
from fdai.delivery.assurance_twin_evidence_conflict import (
    AssuranceTwinEvidenceConflictMixin,
)
from fdai.delivery.assurance_twin_review_evidence import AssuranceTwinReviewEvidenceMixin
from fdai.delivery.assurance_twin_writers import (
    REQUEST_TOPIC,
    AssuranceTwinPublishRequest,
    RetainedTwinEvidence,
    request_key,
)
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    evidence_body_digest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.projection import Finding
from fdai.shared.providers.state_store import AssuranceTwinConfirmationStore, StateStore

_PREFIX = "runtime:assurance-twin-evidence:"
_MAX_PENDING = 1_000
_LOG = logging.getLogger(__name__)


class StateStoreTwinEvidenceRepository(
    AssuranceTwinReviewEvidenceMixin,
    AssuranceTwinEvidenceConflictMixin,
):
    """Persist complete producer evidence and serve exact read-only writer snapshots.

    Posture evidence comes from Heimdall's retained Inventory pass. Review evidence
    comes only from Forseti's typed ActionType proposal review; see
    :class:`AssuranceTwinReviewEvidenceMixin`.
    """

    def __init__(self, *, store: StateStore) -> None:
        self._store = store
        self._clock = StateStoreTwinEvidenceClock(store=store)

    async def record_posture(
        self,
        *,
        scope: str,
        source_revision: str,
        findings: tuple[Finding, ...],
        evaluated_rule_ids: tuple[str, ...],
        coverage_refs: tuple[str, ...],
        generated_at: datetime,
        fresh_until: datetime,
        correlation_id: str,
        rule_set_revision: str | None = None,
        rule_generation_revision: str | None = None,
        inventory_revision: str | None = None,
    ) -> AssuranceTwinPublishRequest:
        """Record one complete exact-revision Rule assessment without inferring clear."""
        _validate_common(
            source_key=scope,
            source_revision=source_revision,
            evaluated_rule_ids=evaluated_rule_ids,
            coverage_refs=coverage_refs,
            generated_at=generated_at,
            fresh_until=fresh_until,
            correlation_id=correlation_id,
        )
        _validate_findings(findings, evaluated_rule_ids)
        if rule_set_revision is not None and not _digest(rule_set_revision):
            raise ValueError("Assurance Twin Rule set revision is invalid")
        if rule_generation_revision is not None and not _digest(rule_generation_revision):
            raise ValueError("Assurance Twin Rule generation revision is invalid")
        if inventory_revision is not None and not _digest(inventory_revision):
            raise ValueError("Assurance Twin Inventory revision is invalid")
        request = _request(
            kind="posture",
            source_key=scope,
            source_revision=source_revision,
            correlation_id=correlation_id,
        )
        generated_at = await self._clock.stable_generated_at(
            request,
            proposed=generated_at,
            fresh_until=fresh_until,
        )
        _validate_common(
            source_key=scope,
            source_revision=source_revision,
            evaluated_rule_ids=evaluated_rule_ids,
            coverage_refs=coverage_refs,
            generated_at=generated_at,
            fresh_until=fresh_until,
            correlation_id=correlation_id,
        )
        report = build_posture_assessment_report(
            scope=scope,
            generated_at=generated_at.astimezone(UTC).isoformat(),
            mode=Mode.SHADOW,
            findings=findings,
        )
        body = {
            **report.to_dict(),
            "generated_at": generated_at.astimezone(UTC).isoformat(),
            "freshness": "fresh",
            "reason_codes": [],
        }
        value = {
            "kind": "assurance_twin_retained_posture",
            "revision": 1,
            "request": request.model_dump(mode="json"),
            "request_status": "pending",
            "writer_status": "pending",
            "source_revision": source_revision,
            "fresh_until": fresh_until.astimezone(UTC).isoformat(),
            "coverage_refs": list(coverage_refs),
            "complete": True,
            "conflict": False,
            "rule_assessment": rule_assessment_body(
                source_revision=source_revision,
                findings=findings,
                evaluated_rule_ids=evaluated_rule_ids,
                coverage_refs=coverage_refs,
                rule_set_revision=rule_set_revision,
                rule_generation_revision=rule_generation_revision,
                inventory_revision=inventory_revision,
            ),
            "record": body,
            "evidence_digest": evidence_body_digest(body),
        }
        written = await self._write_exact(request, value)
        try:
            await self._clock.release(request)
        except AssuranceTwinEvidenceClockContentionError:
            _LOG.warning(
                "assurance_twin_evidence_clock_release_deferred",
                extra={"kind": request.kind},
            )
        return written

    async def read_posture(self, scope: str, revision: str) -> RetainedTwinEvidence | None:
        return await self._read("posture", scope, revision)

    async def read_review(self, review_key: str, revision: str) -> RetainedTwinEvidence | None:
        return await self._read("review", review_key, revision)

    async def pending_requests(
        self, *, offset: int = 0
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        return await self._store.read_state_page(
            _PREFIX,
            limit=_MAX_PENDING,
            offset=offset,
            field="request_status",
            value="pending",
        )

    async def writer_disposition(
        self, request: AssuranceTwinPublishRequest
    ) -> Literal["published", "superseded", "conflict", "expired", "pending"]:
        source = await self._store.read_state(_state_key(request))
        if source is None:
            return "pending"
        target_key = (
            f"runtime:assurance-twin-posture:{request.source_key}"
            if request.kind == "posture"
            else f"runtime:assurance-twin-review:{request.source_key}"
        )
        retained = await self._store.read_state(target_key)
        source_record = source.get("record")
        source_generated = (
            source_record.get("generated_at") if isinstance(source_record, Mapping) else None
        )
        retained_generated = retained.get("generated_at") if retained is not None else None
        try:
            source_time = (
                datetime.fromisoformat(source_generated)
                if isinstance(source_generated, str)
                else None
            )
            retained_time = (
                datetime.fromisoformat(retained_generated)
                if isinstance(retained_generated, str)
                else None
            )
        except ValueError:
            source_time = retained_time = None
        if source.get("conflict") is True:
            if retained is not None and retained.get("conflict") is not None:
                if source_time is not None and retained_time is not None:
                    return "pending" if retained_time < source_time else "conflict"
                return "pending"
            if source_time is not None and retained_time is not None:
                if retained_time > source_time:
                    return "superseded"
            return "pending"
        if (
            retained is not None
            and retained.get("conflict") is None
            and retained.get("evidence_source_revision") == request.source_revision
            and retained.get("evidence_digest") == source.get("evidence_digest")
            and source.get("writer_status") == "confirmed"
        ):
            return "published"
        rule_assessment = source.get("rule_assessment")
        if (
            not isinstance(rule_assessment, Mapping)
            or not _digest(str(rule_assessment.get("rule_membership_digest") or ""))
            or not _digest(str(rule_assessment.get("rule_generation_digest") or ""))
        ):
            return "conflict"
        try:
            fresh_until = datetime.fromisoformat(str(source.get("fresh_until") or ""))
        except ValueError:
            return "conflict"
        if fresh_until.tzinfo is None or fresh_until <= datetime.now(UTC):
            return "expired"
        if retained is None:
            return "pending"
        if retained.get("conflict") is not None:
            if source_time is not None and retained_time is not None:
                return "pending" if retained_time < source_time else "conflict"
            return "pending"
        if source_time is not None and retained_time is not None and retained_time > source_time:
            return "superseded"
        return "pending"

    async def confirm_writer(
        self,
        request: AssuranceTwinPublishRequest,
        *,
        evidence_digest: str,
    ) -> bool:
        """Record source confirmation only after the writer target commit."""
        if not isinstance(self._store, AssuranceTwinConfirmationStore):
            raise RuntimeError("Assurance Twin source confirmation store is unavailable")
        key = _state_key(request)
        for _attempt in range(3):
            source = await self._store.read_state(key)
            if (
                source is None
                or source.get("conflict") is True
                or source.get("request_status") != "pending"
            ):
                return False
            if source.get("evidence_digest") != evidence_digest:
                return False
            try:
                fresh_until = datetime.fromisoformat(str(source.get("fresh_until") or ""))
            except ValueError:
                return False
            if fresh_until.tzinfo is None or fresh_until <= datetime.now(UTC):
                return False
            target_key = (
                f"runtime:assurance-twin-posture:{request.source_key}"
                if request.kind == "posture"
                else f"runtime:assurance-twin-review:{request.source_key}"
            )
            target = await self._store.read_state(target_key)
            if (
                target is None
                or target.get("conflict") is not None
                or target.get("evidence_digest") != evidence_digest
                or target.get("evidence_source_revision") != request.source_revision
            ):
                return False
            if (
                source.get("writer_status") == "confirmed"
                and target.get("source_confirmed") is True
            ):
                return True
            source_revision = source.get("revision")
            target_revision = target.get("revision")
            if (
                not isinstance(source_revision, int)
                or isinstance(source_revision, bool)
                or not isinstance(target_revision, int)
                or isinstance(target_revision, bool)
            ):
                raise ValueError("Assurance Twin evidence revision is invalid")
            source_confirmed = {
                **dict(source),
                "revision": source_revision + 1,
                "writer_status": "confirmed",
            }
            target_confirmed = {
                **dict(target),
                "revision": target_revision + 1,
                "source_confirmed": True,
                **_advance_target_outbox(target, revision=target_revision + 1),
            }
            if await self._store.confirm_assurance_twin_source(
                source_key=key,
                source_value=source_confirmed,
                expected_source_revision=source_revision,
                target_key=target_key,
                target_value=target_confirmed,
                expected_target_revision=target_revision,
                require_fresh=True,
                audit_entry={
                    "kind": "assurance_twin_evidence_writer_confirmed",
                    "producer_principal": ("Heimdall" if request.kind == "posture" else "Forseti"),
                    "idempotency_key": request.idempotency_key,
                    "source_revision": request.source_revision,
                    "evidence_digest": evidence_digest,
                    "execution_authority": False,
                },
            ):
                return (
                    await self._store.read_state(key) == source_confirmed
                    and await self._store.read_state(target_key) == target_confirmed
                )
        return False

    async def mark_request_published(
        self, request: AssuranceTwinPublishRequest, *, expected_revision: int
    ) -> bool:
        if not isinstance(self._store, AssuranceTwinConfirmationStore):
            raise RuntimeError("Assurance Twin publication confirmation store is unavailable")
        source_key = _state_key(request)
        source = await self._store.read_state(source_key)
        target_key = (
            f"runtime:assurance-twin-posture:{request.source_key}"
            if request.kind == "posture"
            else f"runtime:assurance-twin-review:{request.source_key}"
        )
        target = await self._store.read_state(target_key)
        if (
            source is None
            or target is None
            or source.get("revision") != expected_revision
            or source.get("writer_status") != "confirmed"
            or target.get("conflict") is not None
            or target.get("source_confirmed") is not True
            or target.get("evidence_source_revision") != request.source_revision
            or target.get("evidence_digest") != source.get("evidence_digest")
        ):
            return False
        target_revision = target.get("revision")
        if not isinstance(target_revision, int) or isinstance(target_revision, bool):
            raise ValueError("Assurance Twin target revision is invalid")
        updated = {
            **dict(source),
            "revision": expected_revision + 1,
            "request_status": "published",
        }
        return await self._store.confirm_assurance_twin_source(
            source_key=source_key,
            source_value=updated,
            expected_source_revision=expected_revision,
            target_key=target_key,
            target_value=target,
            expected_target_revision=target_revision,
            require_fresh=False,
            audit_entry={
                "kind": "assurance_twin_evidence_request_published",
                "producer_principal": "assurance-twin-evidence-source",
                "idempotency_key": request.idempotency_key,
                "source_revision": request.source_revision,
                "execution_authority": False,
            },
        )

    async def mark_request_terminal(
        self,
        request: AssuranceTwinPublishRequest,
        *,
        expected_revision: int,
        status: Literal["superseded", "conflict", "expired"],
    ) -> bool:
        return await self._mark_request_terminal(
            request,
            expected_revision=expected_revision,
            status=status,
        )

    async def mark_inventory_superseded(
        self,
        request: AssuranceTwinPublishRequest,
    ) -> bool:
        current = await self._store.read_state(_state_key(request))
        revision = current.get("revision") if current is not None else None
        if not isinstance(revision, int) or isinstance(revision, bool):
            return False
        return await self._mark_request_terminal(
            request,
            expected_revision=revision,
            status="superseded",
        )

    async def _mark_request_terminal(
        self,
        request: AssuranceTwinPublishRequest,
        *,
        expected_revision: int,
        status: Literal["published", "superseded", "conflict", "expired"],
    ) -> bool:
        key = _state_key(request)
        current = await self._store.read_state(key)
        if current is None or current.get("revision") != expected_revision:
            return False
        updated = {
            **dict(current),
            "revision": expected_revision + 1,
            "request_status": status,
        }
        applied = await self._store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=expected_revision,
            audit_entry={
                "kind": f"assurance_twin_evidence_request_{status}",
                "producer_principal": "assurance-twin-evidence-source",
                "idempotency_key": request.idempotency_key,
                "source_revision": request.source_revision,
                "execution_authority": False,
            },
        )
        return applied and await self._store.read_state(key) == updated

    async def _write_exact(
        self,
        request: AssuranceTwinPublishRequest,
        value: Mapping[str, Any],
    ) -> AssuranceTwinPublishRequest:
        key = _state_key(request)
        await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "kind": "assurance_twin_evidence_recorded",
                "producer_principal": ("Heimdall" if request.kind == "posture" else "Forseti"),
                "request_kind": request.kind,
                "idempotency_key": request.idempotency_key,
                "source_revision": request.source_revision,
                "execution_authority": False,
            },
        )
        retained = await self._store.read_state(key)
        if retained is None:
            raise RuntimeError("Assurance Twin retained evidence disappeared")
        if _evidence_identity(retained) != _evidence_identity(value):
            return await self._resolve_source_conflict(
                request=request,
                retained=retained,
                incoming=value,
            )
        return AssuranceTwinPublishRequest.model_validate(retained.get("request"))

    async def _read(
        self,
        kind: Literal["posture", "review"],
        source_key: str,
        revision: str,
    ) -> RetainedTwinEvidence | None:
        request = _request(
            kind=kind,
            source_key=source_key,
            source_revision=revision,
            correlation_id="readback",
        )
        raw = await self._store.read_state(_state_key(request))
        if raw is None:
            return None
        return _decode(raw, expected_kind=kind, source_key=source_key, revision=revision)


class AssuranceTwinEvidenceRequestRelay:
    """Publish only content-free references after durable evidence readback."""

    owner = "EvidenceSource"

    def __init__(
        self,
        *,
        repository: StateStoreTwinEvidenceRepository,
        bus: EventBus,
    ) -> None:
        self._repository = repository
        self._bus = bus
        self._offset = 0

    async def publish_pending(self) -> int:
        published = 0
        rows, total = await self._repository.pending_requests(offset=self._offset)
        if not rows and total and self._offset:
            self._offset = 0
            rows, total = await self._repository.pending_requests()
        for raw in rows:
            request = AssuranceTwinPublishRequest.model_validate(raw.get("request"))
            revision = raw.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool):
                raise ValueError("Assurance Twin evidence revision is invalid")
            disposition = await self._repository.writer_disposition(request)
            if disposition == "published":
                await self._repository.mark_request_published(request, expected_revision=revision)
                continue
            if disposition == "superseded":
                await self._repository.mark_request_terminal(
                    request,
                    expected_revision=revision,
                    status="superseded",
                )
                continue
            if disposition == "conflict":
                await self._repository.mark_request_terminal(
                    request,
                    expected_revision=revision,
                    status="conflict",
                )
                continue
            if disposition == "expired":
                await self._repository.mark_request_terminal(
                    request,
                    expected_revision=revision,
                    status="expired",
                )
                continue
            try:
                await self._bus.publish(
                    REQUEST_TOPIC,
                    request.idempotency_key,
                    request.model_dump(mode="json"),
                )
            except Exception as exc:  # noqa: BLE001 - durable pending state is the retry
                _LOG.warning(
                    "assurance_twin_evidence_request_unacknowledged",
                    extra={"kind": request.kind, "error_type": type(exc).__name__},
                )
                continue
            published += 1
        self._offset = (self._offset + len(rows)) % total if total else 0
        return published

    async def run(self, stop: asyncio.Event, *, interval_seconds: float = 5.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("Assurance Twin evidence relay interval MUST be positive")
        while not stop.is_set():
            await self.publish_pending()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass


def _request(
    *,
    kind: Literal["posture", "review"],
    source_key: str,
    source_revision: str,
    correlation_id: str,
) -> AssuranceTwinPublishRequest:
    return AssuranceTwinPublishRequest(
        kind=kind,
        source_key=source_key,
        source_revision=source_revision,
        correlation_id=correlation_id,
        idempotency_key=request_key(kind, source_key, source_revision),
    )


def _state_key(request: AssuranceTwinPublishRequest) -> str:
    return f"{_PREFIX}{request.idempotency_key.removeprefix('sha256:')}"


__all__ = [
    "AssuranceTwinEvidenceClockCapacityError",
    "AssuranceTwinEvidenceClockContentionError",
    "AssuranceTwinEvidenceExpiredError",
    "AssuranceTwinEvidenceRequestRelay",
    "StateStoreTwinEvidenceRepository",
]
