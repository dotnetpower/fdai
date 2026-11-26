"""Collect content-free runtime log evidence for one exact Kubernetes Pod UID."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Final

from fdai.core.ontology_platform.kubernetes_pod_diagnosis_evidence import (
    KubernetesPodLogEvidence,
)
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProvider,
    LogQueryProviderError,
    LogRecord,
)

_MAX_RECORDS: Final[int] = 128
_MAX_WINDOW: Final[timedelta] = timedelta(hours=24)
_MAX_RECORD_BODY_BYTES: Final[int] = 32_768


class KubernetesPodLogEvidenceCollector:
    """Query an exact Pod UID and discard every raw log body after hashing."""

    def __init__(
        self,
        *,
        provider: LogQueryProvider,
        source_identity: str,
        source_revision: str,
        provider_cutoff: datetime | None = None,
        coverage_receipt_ref: str | None = None,
    ) -> None:
        if (
            not source_identity.strip()
            or len(source_identity) > 512
            or not source_revision.strip()
            or len(source_revision) > 512
        ):
            raise ValueError("Pod log source identity and revision MUST be bounded")
        if (provider_cutoff is None) != (coverage_receipt_ref is None):
            raise ValueError("Pod log provider cutoff and coverage receipt MUST be paired")
        if provider_cutoff is not None and (
            provider_cutoff.tzinfo is None or provider_cutoff.utcoffset() is None
        ):
            raise ValueError("Pod log provider cutoff MUST be timezone-aware")
        if coverage_receipt_ref is not None and (
            not coverage_receipt_ref.strip() or len(coverage_receipt_ref) > 512
        ):
            raise ValueError("Pod log coverage_receipt_ref MUST be bounded non-empty text")
        self._provider = provider
        self._source_identity = source_identity
        self._source_revision = source_revision
        self._provider_cutoff = provider_cutoff
        self._coverage_receipt_ref = coverage_receipt_ref

    async def collect(
        self,
        *,
        pod_uid: str,
        start: datetime,
        end: datetime,
    ) -> KubernetesPodLogEvidence:
        """Return a bounded content-free summary or an explicit provider limitation."""

        if not pod_uid.strip() or len(pod_uid) > 512:
            raise ValueError("Pod log pod_uid MUST be bounded non-empty text")
        if (
            start.tzinfo is None
            or start.utcoffset() is None
            or end.tzinfo is None
            or end.utcoffset() is None
            or start >= end
            or end - start > _MAX_WINDOW
        ):
            raise ValueError("Pod log interval MUST be aware and in (0, 24 hours]")
        records = []
        try:
            async for record in self._provider.query(
                LogQuery(
                    expression="",
                    labels={"pod_uid": pod_uid},
                    since=start,
                    until=end,
                    limit=_MAX_RECORDS + 1,
                )
            ):
                records.append(record)
                if len(records) > _MAX_RECORDS:
                    break
        except LogQueryProviderError:
            return KubernetesPodLogEvidence(
                pod_uid=pod_uid,
                start=start,
                end=end,
                source_identity=self._source_identity,
                complete=False,
                limitation="source_unavailable",
                total_records=0,
                error_records=0,
                first_recorded_at=None,
                last_recorded_at=None,
                record_digests=(),
                evidence_refs=(f"pod-log-source:{self._source_identity}",),
                source_revision=self._source_revision,
            )
        if any(record.labels.get("pod_uid") != pod_uid for record in records):
            return self._unavailable(
                pod_uid=pod_uid,
                start=start,
                end=end,
                limitation="pod_uid_scope_unverified",
            )
        if any(record.at.tzinfo is None or not start <= record.at <= end for record in records):
            return self._unavailable(
                pod_uid=pod_uid,
                start=start,
                end=end,
                limitation="record_time_scope_invalid",
            )
        if any(len(record.body.encode("utf-8")) > _MAX_RECORD_BODY_BYTES for record in records):
            return self._unavailable(
                pod_uid=pod_uid,
                start=start,
                end=end,
                limitation="record_body_oversized",
            )
        if not records:
            return self._unavailable(
                pod_uid=pod_uid,
                start=start,
                end=end,
                limitation="zero_records_unverified",
            )
        truncated = len(records) > _MAX_RECORDS
        bounded = tuple(
            sorted(
                records[:_MAX_RECORDS],
                key=lambda record: (record.at, _record_digest(record)),
            )
        )
        digests = tuple(_record_digest(record) for record in bounded)
        timestamps = tuple(record.at for record in bounded)
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    f"pod-log-source:{self._source_identity}",
                    *(f"pod-log-record:{digest.removeprefix('sha256:')}" for digest in digests),
                )
            )
        )
        limitation = (
            "result_truncated"
            if truncated
            else ("provider_coverage_unverified" if self._coverage_receipt_ref is None else None)
        )
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *evidence_refs,
                    *((self._coverage_receipt_ref,) if self._coverage_receipt_ref else ()),
                )
            )
        )
        return KubernetesPodLogEvidence(
            pod_uid=pod_uid,
            start=start,
            end=end,
            source_identity=self._source_identity,
            complete=limitation is None,
            limitation=limitation,
            total_records=len(bounded),
            error_records=sum(
                record.severity.casefold() in {"error", "critical"} for record in bounded
            ),
            first_recorded_at=min(timestamps) if timestamps else None,
            last_recorded_at=max(timestamps) if timestamps else None,
            record_digests=digests,
            evidence_refs=evidence_refs,
            source_revision=self._source_revision,
            provider_cutoff=self._provider_cutoff,
            coverage_receipt_ref=self._coverage_receipt_ref,
        )

    def _unavailable(
        self,
        *,
        pod_uid: str,
        start: datetime,
        end: datetime,
        limitation: str,
    ) -> KubernetesPodLogEvidence:
        return KubernetesPodLogEvidence(
            pod_uid=pod_uid,
            start=start,
            end=end,
            source_identity=self._source_identity,
            complete=False,
            limitation=limitation,
            total_records=0,
            error_records=0,
            first_recorded_at=None,
            last_recorded_at=None,
            record_digests=(),
            evidence_refs=(f"pod-log-source:{self._source_identity}",),
            source_revision=self._source_revision,
        )


def _record_digest(record: LogRecord) -> str:
    payload = {
        "at": record.at.isoformat(),
        "body_digest": hashlib.sha256(record.body.encode("utf-8")).hexdigest(),
        "severity": record.severity,
        "labels": dict(sorted(record.labels.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


__all__ = ["KubernetesPodLogEvidenceCollector"]
