"""Azure runtime-call telemetry source tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from fdai.core.ontology_platform.runtime_call_telemetry import (
    AuthenticatedRuntimeCallContext,
    RuntimeCallTelemetryEnvelope,
    RuntimeCallTelemetryProducer,
)
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.runtime_call_telemetry import (
    AzureContainerAppRevisionVerifier,
    AzureMonitorRuntimeCallAuthenticator,
    AzureMonitorRuntimeCallContextProvider,
    AzureRuntimeCallTelemetrySource,
)
from fdai.shared.providers.observation import LogQueryResult
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
CALLER_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/rg-example/providers/Microsoft.App/containerApps/ca-example-operator"
)
TARGET_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/"
    "resourceGroups/rg-example/providers/Microsoft.App/containerApps/ca-example-core"
)


class _Provider:
    def __init__(self, result: LogQueryResult) -> None:
        self.result = result

    async def query_log(self, *, query: str, window: str, max_rows: int) -> LogQueryResult:
        assert "caller_resource_id" in query
        assert "ContainerAppConsoleLogs_CL" in query
        assert "runtime_call_endpoint_observed" in query
        assert "arg_max" not in query
        assert "AppRequests" not in query
        assert "AppDependencies" not in query
        assert window == "PT360S"
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


class _EndpointVerifier:
    def __init__(self, *, verified: bool = True, delay_seconds: float = 0) -> None:
        self.verified = verified
        self.delay_seconds = delay_seconds
        self.calls = 0

    async def verify(
        self,
        *,
        resource_id: str,
        revision_name: str,
        replica_name: str,
    ) -> bool:
        assert resource_id.startswith("/subscriptions/")
        assert "--" in revision_name
        assert replica_name.startswith("replica-")
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self.verified


def _source(
    result: LogQueryResult,
    *,
    endpoint_verifier: _EndpointVerifier | None = None,
    endpoint_verification_deadline_seconds: float = 30,
    clock: Callable[[], datetime] | None = None,
) -> AzureRuntimeCallTelemetrySource:
    return AzureRuntimeCallTelemetrySource(
        provider=_Provider(result),
        context_provider=_ContextProvider(),
        endpoint_verifier=endpoint_verifier or _EndpointVerifier(),
        scope_ref="scope:example",
        clock=clock or (lambda: NOW),
        endpoint_verification_deadline_seconds=endpoint_verification_deadline_seconds,
    )


def _row(
    *,
    observation_id: str = "sha256:" + "a" * 64,
    caller_resource_id: str = CALLER_ID,
    target_resource_id: str = TARGET_ID,
    observed_at: datetime = NOW - timedelta(seconds=30),
    endpoint_role: str = "caller",
    platform_resource_id: str | None = None,
    platform_name: str | None = None,
    platform_revision_name: str | None = None,
    platform_replica_name: str | None = None,
    source_container_group_id: str = "container-group",
    source_container_id: str = "container",
    source_platform_timestamp: str = "1788948000.0",
) -> dict[str, object]:
    resolved_platform_name = (
        platform_name
        if platform_name is not None
        else "ca-example-operator"
        if endpoint_role == "caller"
        else "ca-example-core"
    )
    resolved_platform_resource_id = (
        platform_resource_id
        if platform_resource_id is not None
        else caller_resource_id
        if endpoint_role == "caller"
        else target_resource_id
    )
    resolved_revision_name = (
        platform_revision_name
        if platform_revision_name is not None
        else f"{resolved_platform_name}--revision"
    )
    resolved_replica_name = (
        platform_replica_name if platform_replica_name is not None else f"replica-{endpoint_role}"
    )
    return {
        "observation_id": observation_id,
        "schema_version": "fdai.runtime-call-endpoint-log@1.0.0",
        "caller_resource_id": caller_resource_id,
        "target_resource_id": target_resource_id,
        "observed_at": observed_at,
        "endpoint_role": endpoint_role,
        "platform_resource_id": resolved_platform_resource_id,
        "platform_name": resolved_platform_name,
        "platform_revision_name": resolved_revision_name,
        "platform_replica_name": resolved_replica_name,
        "execution_authority": False,
        "mutation_authority": False,
        "source_container_group_id": source_container_group_id,
        "source_container_id": source_container_id,
        "source_platform_timestamp": source_platform_timestamp,
        "table_name": "ContainerAppConsoleLogs_CL",
    }


async def test_collects_exact_runtime_call_endpoints_as_authenticated_records() -> None:
    batch = await _source(
        LogQueryResult(
            rows=(
                _row(
                    observation_id="sha256:" + "1" * 64,
                    observed_at=NOW - timedelta(seconds=20),
                    source_container_id="caller-older",
                ),
                _row(
                    observation_id="sha256:" + "1" * 64,
                    endpoint_role="target",
                    observed_at=NOW - timedelta(seconds=19),
                    source_container_id="target-older",
                ),
                _row(
                    observation_id="sha256:" + "2" * 64,
                    observed_at=NOW - timedelta(seconds=10),
                    source_container_id="caller-newer",
                ),
                _row(
                    observation_id="sha256:" + "2" * 64,
                    endpoint_role="target",
                    observed_at=NOW - timedelta(seconds=9),
                    source_container_id="target-newer",
                ),
            )
        )
    ).collect(None)

    assert batch.complete is True
    assert batch.observed_at == NOW
    assert len(batch.records) == 1
    record = batch.records[0]
    assert record.envelope.observation_id == "sha256:" + "2" * 64
    assert record.envelope.caller_resource_ids == (to_neutral_id(CALLER_ID),)
    assert record.envelope.target_resource_ids == (to_neutral_id(TARGET_ID),)
    assert record.envelope.evidence_ref.startswith("sha256:")
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
                _row(target_resource_id=""),
                {key: value for key, value in _row().items() if key != "caller_resource_id"},
            )
        )
    ).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.reason == "telemetry_rows_incomplete"
    assert batch.coverage == {"unavailable_rows": 0, "redacted_rows": 1, "malformed_rows": 1}


async def test_successful_empty_query_keeps_unproven_producer_unavailable() -> None:
    batch = await _source(LogQueryResult(rows=())).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.reason == "telemetry_source_unavailable"


async def test_platform_name_or_resource_type_mismatch_is_incomplete() -> None:
    batch = await _source(
        LogQueryResult(
            rows=(
                _row(platform_name="ca-another-operator"),
                _row(caller_resource_id="resource:caller"),
                _row(source_container_id=""),
                _row(platform_replica_name=""),
                _row(observed_at=NOW + timedelta(seconds=1)),
                {**_row(), "execution_authority": True},
                {**_row(), "schema_version": "fdai.runtime-call-endpoint-log@9.9.9"},
                _row(endpoint_role="peer"),
                _row(target_resource_id=CALLER_ID),
            )
        )
    ).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.coverage == {"unavailable_rows": 0, "redacted_rows": 0, "malformed_rows": 9}


async def test_platform_resource_id_must_match_the_claimed_endpoint() -> None:
    batch = await _source(
        LogQueryResult(
            rows=(
                _row(platform_resource_id=TARGET_ID),
                _row(endpoint_role="target"),
            )
        )
    ).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.coverage == {"unavailable_rows": 0, "redacted_rows": 0, "malformed_rows": 1}


async def test_equal_time_duplicate_order_is_replay_stable() -> None:
    first = _row(
        source_container_id="container-first",
    )
    second = _row(
        source_container_id="container-second",
    )
    target = _row(
        endpoint_role="target",
        source_container_id="container-target",
    )

    forward = await _source(LogQueryResult(rows=(first, second, target))).collect(None)
    reverse = await _source(LogQueryResult(rows=(target, second, first))).collect(None)

    assert len(forward.records) == 1
    assert forward.records == reverse.records


async def test_unpaired_endpoint_witness_is_explicitly_incomplete() -> None:
    caller_only = await _source(
        LogQueryResult(rows=(_row(observed_at=NOW - timedelta(seconds=120)),))
    ).collect(None)
    target_only = await _source(
        LogQueryResult(
            rows=(
                _row(
                    endpoint_role="target",
                    observed_at=NOW - timedelta(seconds=120),
                ),
            )
        )
    ).collect(None)

    for batch in (caller_only, target_only):
        assert batch.complete is False
        assert batch.records == ()
        assert batch.reason == "telemetry_rows_incomplete"
        assert batch.coverage == {
            "unavailable_rows": 1,
            "redacted_rows": 0,
            "malformed_rows": 0,
        }


async def test_recent_unpaired_witness_remains_pending_without_voiding_batch() -> None:
    batch = await _source(LogQueryResult(rows=(_row(),))).collect(None)

    assert batch.complete is True
    assert batch.records == ()
    assert batch.observed_at == NOW


async def test_unverified_platform_revision_is_explicitly_incomplete() -> None:
    rows = (_row(), _row(endpoint_role="target"))

    batch = await _source(
        LogQueryResult(rows=rows),
        endpoint_verifier=_EndpointVerifier(verified=False),
    ).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.coverage == {
        "unavailable_rows": 2,
        "redacted_rows": 0,
        "malformed_rows": 0,
    }


async def test_endpoint_verification_has_one_total_deadline() -> None:
    rows = (_row(), _row(endpoint_role="target"))

    batch = await _source(
        LogQueryResult(rows=rows),
        endpoint_verifier=_EndpointVerifier(delay_seconds=0.05),
        endpoint_verification_deadline_seconds=0.01,
    ).collect(None)

    assert batch.complete is False
    assert batch.reason == "telemetry_deadline_exceeded"
    assert batch.coverage == {"unavailable_rows": 2}


async def test_evaluation_time_is_captured_after_endpoint_verification() -> None:
    state = {"verified": False}
    clock_calls = 0

    class _OrderingVerifier(_EndpointVerifier):
        async def verify(
            self,
            *,
            resource_id: str,
            revision_name: str,
            replica_name: str,
        ) -> bool:
            result = await super().verify(
                resource_id=resource_id,
                revision_name=revision_name,
                replica_name=replica_name,
            )
            state["verified"] = True
            return result

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            assert state["verified"] is True
        return NOW

    batch = await _source(
        LogQueryResult(rows=(_row(), _row(endpoint_role="target"))),
        endpoint_verifier=_OrderingVerifier(),
        clock=clock,
    ).collect(None)

    assert batch.complete is True
    assert batch.observed_at == NOW


async def test_stale_overlap_rows_do_not_consume_replica_budget() -> None:
    verifier = _EndpointVerifier()
    rows = tuple(
        _row(
            observation_id=f"sha256:{index:064x}",
            observed_at=NOW - timedelta(seconds=330),
            platform_revision_name=f"ca-example-operator--revision-{index}",
            platform_replica_name=f"replica-caller-{index}",
        )
        for index in range(33)
    )

    batch = await _source(
        LogQueryResult(rows=rows),
        endpoint_verifier=verifier,
    ).collect(None)

    assert batch.complete is True
    assert batch.records == ()
    assert verifier.calls == 0


async def test_one_observation_cannot_bind_multiple_endpoint_pairs() -> None:
    alternate_target = TARGET_ID.replace("ca-example-core", "ca-example-core-two")
    rows = (
        _row(),
        _row(endpoint_role="target"),
        _row(target_resource_id=alternate_target),
        _row(
            endpoint_role="target",
            target_resource_id=alternate_target,
            platform_name="ca-example-core-two",
        ),
    )

    batch = await _source(LogQueryResult(rows=rows)).collect(None)

    assert batch.complete is False
    assert batch.records == ()
    assert batch.coverage == {
        "unavailable_rows": 0,
        "redacted_rows": 0,
        "malformed_rows": 1,
    }


async def test_reviewed_context_and_authenticator_bind_exact_monitor_evidence() -> None:
    envelope = RuntimeCallTelemetryEnvelope(
        observation_id="sha256:" + "1" * 64,
        caller_resource_ids=(CALLER_ID,),
        target_resource_ids=(TARGET_ID,),
        scope_ref="scope:example",
        observed_at=NOW - timedelta(seconds=30),
        evidence_cutoff=NOW - timedelta(seconds=30),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        source_identity="azure-monitor.container-app-runtime-calls",
        source_revision="2.1.0",
        evidence_ref="sha256:" + "3" * 64,
    )
    context = await AzureMonitorRuntimeCallContextProvider(clock=lambda: NOW).context_for(envelope)

    observation = await RuntimeCallTelemetryProducer(
        authenticator=AzureMonitorRuntimeCallAuthenticator()
    ).produce(envelope=envelope, claimed_context=context)

    assert observation.authentication_ref == context.authentication_ref
    assert context.source_credential_lineage != context.verifier_credential_lineage


async def test_arm_verifier_binds_revision_to_exact_container_app() -> None:
    revision_name = "ca-example-operator--revision"
    replica_name = "ca-example-operator--revision-replica"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.params["api-version"] == "2025-01-01"
        return httpx.Response(
            200,
            json={
                "id": f"{CALLER_ID}/revisions/{revision_name}/replicas/{replica_name}",
                "name": replica_name,
                "properties": {"active": True},
            },
        )

    identity = StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = AzureContainerAppRevisionVerifier(
            identity=identity,
            http_client=client,
        )
        verified = await verifier.verify(
            resource_id=CALLER_ID,
            revision_name=revision_name,
            replica_name=replica_name,
        )

    assert verified is True
