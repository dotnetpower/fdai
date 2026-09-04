"""One-time Teams Workflows diagnostic transport and durable metadata tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai_operator_service.families.iam.contracts import TeamsWorkflowTestCommand
from fdai_operator_service.teams_workflow_binding import LoadedTeamsWorkflowBinding
from fdai_operator_service.teams_workflow_diagnostics import (
    TeamsWorkflowDiagnosticTester,
    TeamsWorkflowProviderResponse,
    TeamsWorkflowTestConflictError,
    TeamsWorkflowTestProviderError,
    validate_teams_workflow_url,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
URL = (
    "https://example.e4.environment.api.powerplatform.com:443/"
    "powerautomate/automations/direct/workflows/"
    "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
    "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
    "&sig=abcdefghijklmnopqrstuvwxyz012345"
)
REGIONAL_URL = (
    "https://example.e4.environment.api.powerplatform.com/"
    "powerautomate/automations/direct/a1/b2/workflows/"
    "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
    "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
    "&sig=abcdefghijklmnopqrstuvwxyz012345"
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: dict[str, object]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        value = self.values.get(key)
        return None if value is None else dict(value)

    async def write_state(self, key: str, value: dict[str, object]) -> None:
        self.values[key] = dict(value)


class MemoryBindingStore:
    def __init__(self) -> None:
        self.values: list[str] = []

    async def save_and_verify(
        self,
        *,
        webhook_url: str,
        request_id: str,
    ) -> LoadedTeamsWorkflowBinding:
        self.values.append(webhook_url)
        return LoadedTeamsWorkflowBinding(
            webhook_url=webhook_url,
            version=f"version-{len(self.values)}",
            endpoint_digest=validate_teams_workflow_url(webhook_url),
        )

    async def load(self) -> LoadedTeamsWorkflowBinding | None:
        if not self.values:
            return None
        webhook_url = self.values[-1]
        return LoadedTeamsWorkflowBinding(
            webhook_url=webhook_url,
            version=f"version-{len(self.values)}",
            endpoint_digest=validate_teams_workflow_url(webhook_url),
        )


def _accepting_post() -> object:
    async def post(_: str, __: object) -> TeamsWorkflowProviderResponse:
        return TeamsWorkflowProviderResponse(202)

    return post


def _command(request_id: str = "teams-test-1") -> TeamsWorkflowTestCommand:
    return TeamsWorkflowTestCommand(
        actor_id="owner-1",
        request_id=request_id,
        webhook_url=URL,
    )


@pytest.mark.parametrize("url", [URL, REGIONAL_URL])
def test_accepts_canonical_and_regional_power_platform_urls(url: str) -> None:
    assert len(validate_teams_workflow_url(url)) == 64


async def test_accepts_fixed_card_and_never_persists_url() -> None:
    store = MemoryStore()
    calls: list[tuple[str, object]] = []

    async def post(url: str, payload: object) -> TeamsWorkflowProviderResponse:
        calls.append((url, payload))
        return TeamsWorkflowProviderResponse(202, "run-1")

    tester = TeamsWorkflowDiagnosticTester(store=store, post=post, clock=lambda: NOW)
    result = await tester.test(_command())

    assert result.accepted is True
    assert result.provider_status == 202
    assert result.workflow_run_id == "run-1"
    assert len(calls) == 1
    stored = next(iter(store.values.values()))
    assert stored["phase"] == "completed"
    assert stored["outcome"] == "accepted"
    assert URL not in repr(stored)
    attachment = calls[0][1]["attachments"][0]  # type: ignore[index]
    assert attachment["contentUrl"] is None


async def test_saves_and_verifies_before_sending_the_test_card() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    calls: list[str] = []

    async def post(url: str, _: object) -> TeamsWorkflowProviderResponse:
        calls.append(url)
        return TeamsWorkflowProviderResponse(202, "run-1")

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=post,
        clock=lambda: NOW,
    )

    result = await tester.save_and_test(_command())

    assert result.saved is True
    assert result.binding_version == "version-1"
    assert bindings.values == [URL]
    assert calls == [URL]
    binding_state = next(
        value
        for value in store.values.values()
        if value["kind"] == "operator.teams-workflow-binding-save"
    )
    assert binding_state["outcome"] == "saved"
    assert URL not in repr(store.values)


async def test_save_and_test_requires_injected_secret_storage() -> None:
    tester = TeamsWorkflowDiagnosticTester(store=MemoryStore(), clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="storage is not configured"):
        await tester.save_and_test(_command())


@pytest.mark.parametrize(
    "command",
    [
        TeamsWorkflowTestCommand(actor_id="", request_id="save-1", webhook_url=URL),
        TeamsWorkflowTestCommand(actor_id="owner-1", request_id="invalid request", webhook_url=URL),
    ],
)
async def test_save_and_test_rejects_invalid_audit_identity(
    command: TeamsWorkflowTestCommand,
) -> None:
    bindings = MemoryBindingStore()
    tester = TeamsWorkflowDiagnosticTester(
        store=MemoryStore(),
        binding_store=bindings,
        clock=lambda: NOW,
    )

    with pytest.raises(ValueError):
        await tester.save_and_test(command)

    assert bindings.values == []


async def test_saved_request_replay_requires_the_same_actor() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()

    async def post(_: str, __: object) -> TeamsWorkflowProviderResponse:
        return TeamsWorkflowProviderResponse(202)

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=post,
        clock=lambda: NOW,
    )
    await tester.save_and_test(_command())

    with pytest.raises(TeamsWorkflowTestConflictError, match="another endpoint"):
        await tester.save_and_test(
            TeamsWorkflowTestCommand(
                actor_id="owner-2",
                request_id="teams-test-1",
                webhook_url=URL,
            )
        )


async def test_describe_returns_metadata_only_and_never_the_saved_url() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    bindings.values.append(URL)
    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        clock=lambda: NOW,
    )

    described = await tester.describe_binding(actor_id="contributor-1")

    assert described is not None
    assert "webhook_url" not in described
    assert URL not in repr(described)
    assert described["binding_version"] == "version-1"
    assert described["observed_at"] == NOW.isoformat()
    # No save record exists for this version, so no saved_at is claimed.
    assert "saved_at" not in described


async def test_describe_reports_saved_at_only_for_the_recorded_version() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=_accepting_post(),
        clock=lambda: NOW,
    )
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="teams-test-1",
            webhook_url=URL,
        )
    )

    described = await tester.describe_binding(actor_id="owner-1")

    assert described is not None
    assert described["saved_at"] == NOW.isoformat()
    assert URL not in repr(store.values)


async def test_missing_binding_describes_as_absent() -> None:
    tester = TeamsWorkflowDiagnosticTester(
        store=MemoryStore(),
        binding_store=MemoryBindingStore(),
        clock=lambda: NOW,
    )

    assert await tester.describe_binding(actor_id="owner-1") is None


async def test_duplicate_completed_request_returns_receipt_without_resend() -> None:
    store = MemoryStore()
    calls = 0

    async def post(_: str, __: object) -> TeamsWorkflowProviderResponse:
        nonlocal calls
        calls += 1
        return TeamsWorkflowProviderResponse(202)

    tester = TeamsWorkflowDiagnosticTester(store=store, post=post, clock=lambda: NOW)

    first = await tester.test(_command())
    second = await tester.test(_command())

    assert first == second
    assert calls == 1


async def test_ambiguous_request_id_is_not_replayed() -> None:
    store = MemoryStore()

    async def post(_: str, __: object) -> TeamsWorkflowProviderResponse:
        raise httpx.ReadTimeout("acknowledgement missing")

    tester = TeamsWorkflowDiagnosticTester(store=store, post=post, clock=lambda: NOW)
    with pytest.raises(TeamsWorkflowTestProviderError, match="not observed"):
        await tester.test(_command())
    with pytest.raises(TeamsWorkflowTestConflictError, match="ambiguous"):
        await tester.test(_command())


@pytest.mark.parametrize(
    "url",
    [
        "http://example.e4.environment.api.powerplatform.com/path?sig=abcdefghijklmnopqrstuvwxyz",
        "https://localhost/powerautomate/automations/direct/workflows/"
        "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
        "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
        "&sig=abcdefghijklmnopqrstuvwxyz012345",
        URL + "&redirect=https://localhost",
    ],
)
def test_rejects_non_power_platform_and_widened_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_teams_workflow_url(url)
