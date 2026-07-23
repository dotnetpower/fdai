"""Artifact-first materialization of forecast outcomes as case revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime

from fdai.shared.contracts.models import ForecastOutcome
from fdai.shared.providers.case_history import (
    CaseHistoryArtifactStore,
    CaseHistoryMetadataStore,
    CaseHistoryRevisionRecord,
)

from .models import CaseKind, CaseSourceRecord, build_case_history_revision


class CaseHistoryMaterializer:
    def __init__(
        self,
        *,
        metadata: CaseHistoryMetadataStore,
        artifacts: CaseHistoryArtifactStore,
    ) -> None:
        self._metadata = metadata
        self._artifacts = artifacts

    async def seal_forecast_outcome(
        self,
        outcome: ForecastOutcome,
        *,
        purpose: str,
        redaction_policy_version: str,
        retention_until: datetime,
        deletion_due_at: datetime,
        additional_sources: Sequence[CaseSourceRecord] = (),
        legal_hold: bool = False,
        legal_hold_ref: str | None = None,
    ) -> CaseHistoryRevisionRecord:
        case_id = _case_id(outcome, purpose=purpose)
        outcome_source = _outcome_source(outcome)
        sources = (outcome_source, *additional_sources)
        source_set_digest = _source_set_digest(sources)
        latest = await self._metadata.latest(
            case_id,
            access_scope_digest=outcome.access_scope_digest,
        )
        if latest is not None and latest.deleted_at is not None:
            raise PermissionError("deleted case history cannot be reopened")
        if latest is not None and latest.deletion_started_at is not None:
            raise PermissionError("case history pending deletion cannot be reopened")
        if latest is not None and latest.source_set_digest == source_set_digest:
            if (
                latest.retention_until != retention_until
                or latest.deletion_due_at != deletion_due_at
                or latest.legal_hold != legal_hold
                or latest.legal_hold_ref != legal_hold_ref
            ):
                raise ValueError("case history governance cannot change on duplicate evidence")
            return latest
        if latest is not None:
            await self._validate_source_continuity(latest, sources)
        revision_number = 1 if latest is None else latest.revision + 1
        parent_digest = None if latest is None else latest.manifest_digest
        sealed_at = max((outcome.closed_at, *(source.occurred_at for source in sources)))
        revision = build_case_history_revision(
            case_id=case_id,
            revision=revision_number,
            kind=CaseKind.PREDICTION,
            correlation_id=outcome.correlation_id,
            purpose=purpose,
            access_scope_digest=outcome.access_scope_digest,
            redaction_policy_version=redaction_policy_version,
            event_time_cutoff=outcome.horizon_ended_at,
            created_by_agent="Muninn",
            sealed_at=sealed_at,
            parent_manifest_digest=parent_digest,
            sources=sources,
        )
        storage_ref = f"case-history/{case_id}/{revision.revision}/{revision.manifest_digest}.json"
        artifact_created = await self._artifacts.put(
            storage_ref,
            revision.artifact_bytes,
            digest=revision.manifest_digest,
        )
        record = CaseHistoryRevisionRecord(
            case_id=case_id,
            revision=revision.revision,
            kind=revision.kind.value,
            correlation_id=outcome.correlation_id,
            purpose=purpose,
            access_scope_digest=outcome.access_scope_digest,
            manifest_digest=revision.manifest_digest,
            parent_manifest_digest=parent_digest,
            source_set_digest=source_set_digest,
            storage_ref=storage_ref,
            artifact_size=len(revision.artifact_bytes),
            outcome_label=outcome.label.value,
            detector_id=outcome.detector_id,
            detector_version=outcome.detector_version,
            metric=outcome.metric,
            event_time_cutoff=outcome.horizon_ended_at,
            created_by_agent="Muninn",
            sealed_at=sealed_at,
            retention_until=retention_until,
            deletion_due_at=deletion_due_at,
            legal_hold=legal_hold,
            legal_hold_ref=legal_hold_ref,
        )
        try:
            created = await self._metadata.append_revision(record)
        except Exception as metadata_error:
            try:
                committed = await self._metadata.latest(
                    case_id,
                    access_scope_digest=outcome.access_scope_digest,
                )
            except Exception as verification_error:
                raise ExceptionGroup(
                    "case history metadata append failed and commit status could not be verified",
                    [metadata_error, verification_error],
                ) from metadata_error
            if committed == record:
                return record
            if artifact_created:
                try:
                    await self._artifacts.delete(storage_ref)
                except Exception as cleanup_error:
                    raise ExceptionGroup(
                        "case history metadata append and artifact cleanup failed",
                        [metadata_error, cleanup_error],
                    ) from metadata_error
            raise
        if not created:
            existing = await self._metadata.latest(
                case_id,
                access_scope_digest=outcome.access_scope_digest,
            )
            if existing is None or existing != record:
                raise RuntimeError("case history idempotent append lost its stored revision")
            return existing
        return record

    async def _validate_source_continuity(
        self,
        latest: CaseHistoryRevisionRecord,
        sources: Sequence[CaseSourceRecord],
    ) -> None:
        if latest.storage_ref is None:
            raise PermissionError("deleted case history cannot be revised")
        content = await self._artifacts.get(latest.storage_ref)
        if content is None or hashlib.sha256(content).hexdigest() != latest.manifest_digest:
            raise ValueError("case history parent artifact is unavailable or invalid")
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("case history parent artifact is unavailable or invalid") from exc
        if (
            not isinstance(document, dict)
            or document.get("case_id") != latest.case_id
            or document.get("revision") != latest.revision
            or document.get("access_scope_digest") != latest.access_scope_digest
        ):
            raise ValueError("case history parent artifact identity is invalid")
        raw_sources = document.get("sources")
        if not isinstance(raw_sources, list):
            raise ValueError("case history parent artifact sources are invalid")
        previous: dict[tuple[str, str], str] = {}
        for raw in raw_sources:
            if not isinstance(raw, dict):
                raise ValueError("case history parent artifact sources are invalid")
            identity = (str(raw.get("record_type") or ""), str(raw.get("record_id") or ""))
            digest = str(raw.get("record_digest") or "")
            if not all(identity) or identity in previous:
                raise ValueError("case history parent artifact sources are invalid")
            previous[identity] = digest
        incoming = {
            (source.record_type, source.record_id): source.record_digest for source in sources
        }
        if any(incoming.get(identity) != digest for identity, digest in previous.items()):
            raise ValueError("case history revision MUST preserve prior source evidence")


class CaseHistoryRetentionService:
    """Delete due artifacts before committing metadata tombstones."""

    def __init__(
        self,
        *,
        metadata: CaseHistoryMetadataStore,
        artifacts: CaseHistoryArtifactStore,
    ) -> None:
        self._metadata = metadata
        self._artifacts = artifacts

    async def delete_due(self, *, now: datetime, limit: int = 500) -> tuple[str, ...]:
        due = await self._metadata.list_due(now=now, limit=limit)
        deleted: list[str] = []
        for record in due:
            if record.legal_hold:
                raise PermissionError("case history due source returned a legal-hold record")
            if record.storage_ref is None:
                raise RuntimeError("active case history record is missing storage_ref")
            storage_refs = record.deletion_storage_refs
            if record.deletion_started_at is None:
                storage_refs = await self._revision_storage_refs(record)
                record = await self._metadata.mark_deletion_started(
                    record.case_id,
                    access_scope_digest=record.access_scope_digest,
                    revision=record.revision,
                    storage_refs=storage_refs,
                    started_at=now,
                )
            for storage_ref in storage_refs:
                await self._artifacts.delete(storage_ref)
            await self._metadata.mark_deleted(
                record.case_id,
                access_scope_digest=record.access_scope_digest,
                revision=record.revision,
                deleted_at=now,
            )
            deleted.append(record.case_id)
        return tuple(deleted)

    async def _revision_storage_refs(
        self,
        record: CaseHistoryRevisionRecord,
    ) -> tuple[str, ...]:
        storage_ref = record.storage_ref
        if storage_ref is None:
            raise RuntimeError("active case history record is missing storage_ref")
        if storage_ref != _storage_ref(record.case_id, record.revision, record.manifest_digest):
            raise ValueError("case history storage_ref does not match its revision identity")
        refs: list[str] = []
        revision = record.revision
        digest = record.manifest_digest
        while True:
            current_ref = _storage_ref(record.case_id, revision, digest)
            content = await self._artifacts.get(current_ref)
            if content is None or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("case history revision chain artifact is unavailable or invalid")
            try:
                document = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "case history revision chain artifact is unavailable or invalid"
                ) from exc
            if (
                not isinstance(document, dict)
                or document.get("case_id") != record.case_id
                or document.get("revision") != revision
                or document.get("access_scope_digest") != record.access_scope_digest
            ):
                raise ValueError("case history revision chain identity is invalid")
            parent = document.get("parent_manifest_digest")
            if revision == record.revision and parent != record.parent_manifest_digest:
                raise ValueError("case history revision chain parent does not match metadata")
            refs.append(current_ref)
            if revision == 1:
                if parent is not None:
                    raise ValueError("case history revision chain root has a parent")
                break
            if not isinstance(parent, str) or len(parent) != 64:
                raise ValueError("case history revision chain parent is missing")
            digest = parent
            revision -= 1
        return tuple(refs)


def _case_id(outcome: ForecastOutcome, *, purpose: str) -> str:
    identity = outcome.prediction_id or outcome.outcome_id
    purpose_digest = hashlib.sha256(purpose.encode()).hexdigest()[:16]
    return f"prediction-{outcome.access_scope_digest}-{identity}-{purpose_digest}"


def _storage_ref(case_id: str, revision: int, manifest_digest: str) -> str:
    return f"case-history/{case_id}/{revision}/{manifest_digest}.json"


def _outcome_source(outcome: ForecastOutcome) -> CaseSourceRecord:
    payload = outcome.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return CaseSourceRecord(
        record_type="forecast-outcome",
        record_id=str(outcome.outcome_id),
        record_digest=hashlib.sha256(canonical).hexdigest(),
        occurred_at=outcome.closed_at,
        payload=payload,
    )


def _source_set_digest(sources: Sequence[CaseSourceRecord]) -> str:
    values = sorted(
        f"{source.record_type}:{source.record_id}:{source.record_digest}" for source in sources
    )
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


__all__ = ["CaseHistoryMaterializer", "CaseHistoryRetentionService"]
