"""Content-free exact-Pod runtime log evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.delivery.kubernetes_pod_log_evidence import KubernetesPodLogEvidenceCollector
from fdai.shared.providers.log_query import (
    LogQuery,
    LogQueryProviderError,
    LogRecord,
    StaticLogQueryProvider,
)

_END = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
_START = _END - timedelta(minutes=15)


async def test_collector_hashes_exact_pod_logs_without_retaining_body() -> None:
    body = "private runtime content"
    provider = StaticLogQueryProvider(
        (
            LogRecord(
                at=_END - timedelta(minutes=2),
                body=body,
                severity="error",
                labels={"pod_uid": "pod-uid-a", "source": "ContainerLogV2"},
            ),
        )
    )

    result = await KubernetesPodLogEvidenceCollector(
        provider=provider,
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is True
    assert result.total_records == 1
    assert result.error_records == 1
    assert len(result.record_digests) == 1
    assert body not in result.record_digests[0]
    assert body not in repr(result)


class _UnavailableProvider:
    async def query(self, query: LogQuery):  # type: ignore[no-untyped-def]
        raise LogQueryProviderError("unavailable")
        yield  # pragma: no cover


class _WideningProvider:
    async def query(self, query: LogQuery):  # type: ignore[no-untyped-def]
        yield LogRecord(
            at=_END - timedelta(minutes=2),
            body="ignored",
            severity="information",
            labels={"pod_uid": "pod-uid-b"},
        )


async def test_collector_surfaces_provider_unavailability() -> None:
    result = await KubernetesPodLogEvidenceCollector(
        provider=_UnavailableProvider(),
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is False
    assert result.limitation == "source_unavailable"
    assert result.total_records == 0


async def test_collector_rejects_provider_scope_widening() -> None:
    result = await KubernetesPodLogEvidenceCollector(
        provider=_WideningProvider(),
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is False
    assert result.limitation == "pod_uid_scope_unverified"
    assert result.total_records == 0


async def test_collector_does_not_treat_zero_rows_as_historical_absence() -> None:
    result = await KubernetesPodLogEvidenceCollector(
        provider=StaticLogQueryProvider(()),
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is False
    assert result.limitation == "zero_records_unverified"
    assert result.total_records == 0


async def test_collector_preserves_duplicate_rows_as_replayable_multiplicity() -> None:
    duplicate = LogRecord(
        at=_END - timedelta(minutes=2),
        body="same line",
        severity="information",
        labels={"pod_uid": "pod-uid-a"},
    )
    result = await KubernetesPodLogEvidenceCollector(
        provider=StaticLogQueryProvider((duplicate, duplicate)),
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is True
    assert result.total_records == 2
    assert result.record_digests[0] == result.record_digests[1]
    assert len(result.evidence_refs) == 2


async def test_collector_rejects_records_outside_the_requested_window() -> None:
    class _OutOfWindowProvider:
        async def query(self, query: LogQuery):  # type: ignore[no-untyped-def]
            yield LogRecord(
                at=_END + timedelta(seconds=1),
                body="ignored",
                severity="information",
                labels={"pod_uid": "pod-uid-a"},
            )

    result = await KubernetesPodLogEvidenceCollector(
        provider=_OutOfWindowProvider(),
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is False
    assert result.limitation == "record_time_scope_invalid"
    assert result.total_records == 0


async def test_collector_stops_after_the_truncation_sentinel() -> None:
    class _UnboundedProvider:
        def __init__(self) -> None:
            self.yielded = 0

        async def query(self, query: LogQuery):  # type: ignore[no-untyped-def]
            for index in range(1_000):
                self.yielded += 1
                yield LogRecord(
                    at=_START + timedelta(seconds=index),
                    body=f"line-{index}",
                    severity="information",
                    labels={"pod_uid": "pod-uid-a"},
                )

    provider = _UnboundedProvider()
    result = await KubernetesPodLogEvidenceCollector(
        provider=provider,
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert provider.yielded == 129
    assert result.complete is False
    assert result.limitation == "result_truncated"
    assert result.total_records == 128


async def test_collector_rejects_an_oversized_log_body() -> None:
    provider = StaticLogQueryProvider(
        (
            LogRecord(
                at=_END - timedelta(minutes=2),
                body="x" * 32_769,
                severity="information",
                labels={"pod_uid": "pod-uid-a"},
            ),
        )
    )

    result = await KubernetesPodLogEvidenceCollector(
        provider=provider,
        source_identity="azure-monitor",
    ).collect(pod_uid="pod-uid-a", start=_START, end=_END)

    assert result.complete is False
    assert result.limitation == "record_body_oversized"
    assert result.total_records == 0
