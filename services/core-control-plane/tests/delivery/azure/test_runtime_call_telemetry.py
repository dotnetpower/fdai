"""Azure runtime-call telemetry source tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
)
from fdai.delivery.azure.runtime_call_telemetry import AzureRuntimeCallTelemetrySource
from fdai.shared.providers.observation import LogQueryResult

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)


class _Provider:
    def __init__(self, result: LogQueryResult) -> None:
        self.result = result

    async def query_log(self, *, query: str, window: str, max_rows: int) -> LogQueryResult:
        assert "caller_resource_id" in query
        assert "AppRequests" in query
        assert "AppDependencies" in query
        assert "isfuzzy" not in query
        assert window == "PT300S"
        assert max_rows == 2000
        return self.result


class _ContextProvider:
    async def context_for(self, envelope):  # type: ignore[no-untyped-def]
        return AuthenticatedRuntimeCallContext(
            observation_id=envelope.observation_id,
            observation_digest=envelope.content_digest(),
            source_identity=envelope.source_identity,
            source_credential_lineage="source-lineage",
            verifier_identity="independent-verifier",
            verifier_credential_lineage="verifier-lineage",
            authentication_ref="sha256:" + "1" * 64,
            verified_at=envelope.recorded_at,
            signature_verified=True,
        )


def _source(result: LogQueryResult) -> AzureRuntimeCallTelemetrySource:
    return AzureRuntimeCallTelemetrySource(
        provider=_Provider(result),
        context_provider=_ContextProvider(),
        scope_ref="scope:example",
    )


async def test_collects_exact_runtime_call_endpoints_as_authenticated_records() -> None:
    batch = await _source(
        LogQueryResult(
            rows=(
                {
                    "observation_id": "span-1",
                    "caller_resource_id": "resource:caller",
                    "target_resource_id": "resource:target",
                    "observed_at": NOW,
                    "table_name": "AppRequests",
                },
                {
                    "observation_id": "span-2",
                    "caller_resource_id": "resource:caller",
                    "target_resource_id": "resource:target",
                    "observed_at": NOW,
                    "table_name": "AppDependencies",
                },
            )
        )
    ).collect(None)

    assert batch.complete is True
    assert len(batch.records) == 2
    record = batch.records[0]
    assert record.envelope.caller_resource_ids == ("resource:caller",)
    assert record.envelope.target_resource_ids == ("resource:target",)
    assert record.claimed_context.observation_digest == record.envelope.content_digest()


async def test_truncated_runtime_call_source_is_explicitly_incomplete() -> None:
    batch = await _source(LogQueryResult(rows=(), truncated=True)).collect(None)

    assert batch.records == ()
    assert batch.complete is False
    assert batch.reason == "telemetry_rows_incomplete"
    assert batch.coverage == {"unavailable_rows": 1}


async def test_partial_rows_are_reported_and_never_returned_as_complete() -> None:
    batch = await _source(
        LogQueryResult(
            rows=(
                {
                    "observation_id": "span-1",
                    "caller_resource_id": "resource:caller",
                    "target_resource_id": "",
                    "observed_at": NOW,
                    "table_name": "AppRequests",
                },
                {
                    "observation_id": "span-2",
                    "caller_resource_id": "resource:caller",
                    "observed_at": NOW,
                    "table_name": "AppDependencies",
                },
            )
        )
    ).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.reason == "telemetry_rows_incomplete"
    assert batch.coverage == {"unavailable_rows": 0, "redacted_rows": 1, "malformed_rows": 1}


async def test_missing_table_coverage_is_unavailable_even_when_no_rows_return() -> None:
    batch = await _source(LogQueryResult(rows=())).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.coverage == {"unavailable_rows": 1, "redacted_rows": 0, "malformed_rows": 0}
