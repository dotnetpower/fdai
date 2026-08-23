"""Focused tests for optional Azure MCP read transport and fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fdai.delivery.azure.mcp_read_investigation import (
    AzureMcpClient,
    AzureMcpReadBinding,
    AzureMcpReadInvestigationProvider,
    resource_health_binding,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceAttempt,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadToolId,
    ReadToolLimits,
    ResolvedResource,
)
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt
from fdai.shared.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig


class _Session:
    def __init__(
        self,
        *,
        tools: tuple[str, ...],
        fail_call: bool = False,
        structured_content: dict[str, object] | None = None,
    ) -> None:
        self.tools = tools
        self.fail_call = fail_call
        self.structured_content = structured_content or {"status": "matched"}
        self.calls = 0

    async def list_tools(self) -> object:
        return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in self.tools])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> object:
        del name, arguments, read_timeout_seconds
        self.calls += 1
        if self.fail_call:
            raise ConnectionError("MCP unavailable")
        return SimpleNamespace(is_error=False, structured_content=self.structured_content)


class _Context:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        del args


class _Base:
    transport = "rest"

    def __init__(self) -> None:
        self.calls = 0

    async def query_network_security(
        self, resource: ResolvedResource, *, limits: ReadToolLimits
    ) -> ReadEvidenceAttempt:
        del limits
        self.calls += 1
        return _attempt(ReadToolId.QUERY_NETWORK_SECURITY, resource, "rest")


def _attempt(
    tool_id: ReadToolId,
    resource: ResolvedResource,
    transport: str,
) -> ReadEvidenceAttempt:
    return ReadEvidenceAttempt(
        tool_id=tool_id,
        evidence=ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED,
            authority="network_security",
            resource_ref=resource.resource_ref,
            observed_at=datetime.now(UTC),
            freshness=EvidenceFreshness.LIVE,
            truncated=False,
            records=(
                ReadEvidenceRecord(
                    occurred_at=datetime.now(UTC),
                    status="observed",
                    details=(("rule_count", "1"),),
                ),
            ),
            evidence_refs=("evidence:one",),
        ),
        receipt=ToolCallReceipt(
            ToolCallOutcome.SUCCEEDED,
            f"{transport}:one",
            tool_id=tool_id.value,
            transport=transport,
            operation_class="network_security",
        ),
    )


def _provider(
    session: _Session,
    base: _Base,
    *,
    circuit: CircuitBreaker | None = None,
) -> AzureMcpReadInvestigationProvider:
    client = AzureMcpClient(sessions=lambda: _Context(session))
    return AzureMcpReadInvestigationProvider(
        base=base,  # type: ignore[arg-type]
        client=client,
        bindings=(
            AzureMcpReadBinding(
                tool_id=ReadToolId.QUERY_NETWORK_SECURITY,
                tool_name="network_nsg_get",
                arguments=lambda resource, lookback, limits: {
                    "name": resource.name,
                    "limit": limits.max_results,
                },
                normalize=lambda payload, resource, limits: _attempt(
                    ReadToolId.QUERY_NETWORK_SECURITY,
                    resource,
                    "azure_mcp",
                ),
            ),
        ),
        circuit=circuit,
    )


async def test_discovery_enables_only_complete_allowlist_and_uses_mcp() -> None:
    session = _Session(tools=("network_nsg_get",))
    base = _Base()
    provider = _provider(session, base)
    resource = ResolvedResource("resource-one", "scope-one", "nsg-one", "network.nsg", "group-one")

    assert await provider.discover() is True
    attempt = await provider.query_network_security(
        resource,
        limits=ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096),
    )

    assert attempt.receipt.transport == "azure_mcp"
    assert session.calls == 1
    assert base.calls == 0


async def test_missing_tool_or_call_failure_falls_back_without_widening() -> None:
    resource = ResolvedResource("resource-one", "scope-one", "nsg-one", "network.nsg", "group-one")
    limits = ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096)

    missing_base = _Base()
    missing = _provider(_Session(tools=()), missing_base)
    assert await missing.discover() is False
    assert (await missing.query_network_security(resource, limits=limits)).receipt.transport == (
        "rest"
    )

    failing_session = _Session(tools=("network_nsg_get",), fail_call=True)
    failing_base = _Base()
    failing = _provider(
        failing_session,
        failing_base,
        circuit=CircuitBreaker(
            name="azure-mcp-test",
            config=CircuitBreakerConfig(failure_threshold=1, reset_timeout_s=60),
        ),
    )
    assert await failing.discover() is True
    assert (await failing.query_network_security(resource, limits=limits)).receipt.transport == (
        "rest"
    )
    assert (await failing.query_network_security(resource, limits=limits)).receipt.transport == (
        "rest"
    )
    assert failing_session.calls == 1
    assert failing_base.calls == 2


async def test_discovery_preserves_each_available_allowlisted_tool() -> None:
    session = _Session(tools=("resourcehealth_availability-status_get",))
    client = AzureMcpClient(sessions=lambda: _Context(session))

    discovered = await client.discover(
        frozenset(
            {
                "resourcehealth_availability-status_get",
                "network_nsg_get",
            }
        )
    )

    assert discovered == frozenset({"resourcehealth_availability-status_get"})


def test_resource_health_binding_uses_exact_id_and_normalizes_bounded_state() -> None:
    binding = resource_health_binding()
    resource = ResolvedResource(
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/example/providers/Microsoft.Compute/virtualMachines/vm-one",
        "scope-one",
        "vm-one",
        "compute.vm",
        "example",
    )
    limits = ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=4096)

    arguments = binding.arguments(resource, 3600, limits)
    attempt = binding.normalize(
        {
            "id": resource.resource_ref,
            "properties": {"availabilityState": "Degraded"},
        },
        resource,
        limits,
    )

    assert arguments == {
        "auth-method": "Credential",
        "resourceId": resource.resource_ref,
        "retry-max-retries": 0,
        "retry-network-timeout": 5,
    }
    assert attempt.evidence.resource_ref == resource.resource_ref
    assert attempt.evidence.records[0].state == "degraded"
    assert attempt.receipt.transport == "azure_mcp"


async def test_plan_output_bound_falls_back_before_normalization() -> None:
    session = _Session(
        tools=("network_nsg_get",),
        structured_content={"status": "matched", "padding": "x" * 5_000},
    )
    base = _Base()
    provider = _provider(session, base)
    resource = ResolvedResource("resource-one", "scope-one", "nsg-one", "network.nsg", "group-one")
    assert await provider.discover() is True

    attempt = await provider.query_network_security(
        resource,
        limits=ReadToolLimits(timeout_seconds=5, max_results=8, max_output_bytes=1024),
    )

    assert attempt.receipt.transport == "rest"
    assert session.calls == 1
    assert base.calls == 1
