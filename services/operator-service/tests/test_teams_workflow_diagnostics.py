"""One-time Teams Workflows diagnostic transport and durable metadata tests."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fdai_operator_service.families.iam.contracts import TeamsWorkflowTestCommand
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
