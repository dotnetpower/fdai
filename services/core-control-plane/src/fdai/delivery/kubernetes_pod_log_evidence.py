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

    def __init__(self, *, provider: LogQueryProvider, source_identity: str) -> None:
        if not source_identity.strip() or len(source_identity) > 512:
            raise ValueError("Pod log source_identity MUST be bounded non-empty text")
        self._provider = provider
        self._source_identity = source_identity

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
        if start.tzinfo is None or end.tzinfo is None or start >= end or end - start > _MAX_WINDOW:
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
        return KubernetesPodLogEvidence(
            pod_uid=pod_uid,
            start=start,
            end=end,
            source_identity=self._source_identity,
            complete=not truncated,
            limitation="result_truncated" if truncated else None,
            total_records=len(bounded),
            error_records=sum(
                record.severity.casefold() in {"error", "critical"} for record in bounded
            ),
            first_recorded_at=min(timestamps) if timestamps else None,
            last_recorded_at=max(timestamps) if timestamps else None,
            record_digests=digests,
            evidence_refs=evidence_refs,
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
