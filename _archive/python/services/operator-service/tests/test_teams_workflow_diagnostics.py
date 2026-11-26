"""One-time Teams Workflows diagnostic transport and durable metadata tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from fdai_operator_service.families.iam.contracts import TeamsWorkflowTestCommand
from fdai_operator_service.teams_workflow_binding import LoadedTeamsWorkflowBinding
from fdai_operator_service.teams_workflow_diagnostics import (
    TeamsWorkflowBindingUnavailableError,
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
    card_content = attachment["content"]
    assert card_content["msteams"] == {"width": "Full"}
    hero_image = card_content["body"][0]
    assert hero_image["type"] == "Image"
    assert hero_image["url"].startswith("data:image/png;base64,")
    assert URL not in repr(calls[0][1])


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


async def test_save_survives_a_provider_rejection() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()

    async def reject(_: str, __: object) -> TeamsWorkflowProviderResponse:
        return TeamsWorkflowProviderResponse(400)

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=reject,
        clock=lambda: NOW,
    )

    result = await tester.save_and_test(_command())
    described = await tester.describe_binding(actor_id="owner-1")

    assert result.saved is True
    assert result.accepted is False
    assert result.provider_status == 400
    assert described is not None
    assert described["binding_version"] == "version-1"
    assert described["saved_at"] == NOW.isoformat()
    assert bindings.values == [URL]
    assert URL not in repr(store.values)


async def test_empty_url_retests_the_saved_binding_without_replacing_it() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    calls: list[str] = []

    async def post(url: str, _: object) -> TeamsWorkflowProviderResponse:
        calls.append(url)
        return TeamsWorkflowProviderResponse(202, "run-2")

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=post,
        clock=lambda: NOW,
    )
    await tester.save_and_test(_command("teams-save-1"))
    calls.clear()

    result = await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="teams-retest-1",
            webhook_url="",
        )
    )

    assert result.saved is True
    assert result.accepted is True
    assert result.binding_version == "version-1"
    assert calls == [URL]
    assert bindings.values == [URL]


async def test_empty_url_requires_an_existing_saved_binding() -> None:
    tester = TeamsWorkflowDiagnosticTester(
        store=MemoryStore(),
        binding_store=MemoryBindingStore(),
        clock=lambda: NOW,
    )

    with pytest.raises(TeamsWorkflowBindingUnavailableError, match="not configured"):
        await tester.save_and_test(
            TeamsWorkflowTestCommand(
                actor_id="owner-1",
                request_id="teams-retest-1",
                webhook_url="",
            )
        )


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
    digest = hashlib.sha256(URL.encode("utf-8")).hexdigest()
    assert described["endpoint_identifier"] == (f"workflow ...da483a70 / sha256:{digest[:12]}")
    assert described["observed_at"] == NOW.isoformat()
    # No save record exists for this version, so no saved_at is claimed.
    assert "saved_at" not in described
    assert "sig=" not in repr(described)
    assert "environment.api.powerplatform.com" not in repr(described)
    assert URL not in repr(described)


async def test_reveal_binding_audits_secret_free_record_and_returns_url() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    bindings.values.append(URL)
    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        clock=lambda: NOW,
    )

    revealed = await tester.reveal_binding(actor_id="contributor-1")

    assert revealed is not None
    assert revealed["webhook_url"] == URL
    assert revealed["binding_version"] == "version-1"
    assert revealed["revealed_at"] == NOW.isoformat()
    audit_record = next(
        value
        for value in store.values.values()
        if value["kind"] == "operator.teams-workflow-binding-reveal"
    )
    assert audit_record["actor_id"] == "contributor-1"
    assert audit_record["outcome"] == "revealed"
    assert URL not in repr(store.values)


async def test_multi_channel_selection_and_simultaneous_fanout() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    called_urls: list[str] = []

    async def post(url: str, _: object) -> TeamsWorkflowProviderResponse:
        called_urls.append(url)
        return TeamsWorkflowProviderResponse(202, "run-multi")

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=post,
        clock=lambda: NOW,
    )
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="save-ch-1",
            webhook_url=URL,
            channel_label="Ops Alerts",
        )
    )
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="save-ch-2",
            webhook_url=REGIONAL_URL,
            channel_label="Daily Digest",
        )
    )

    described = await tester.describe_binding(actor_id="owner-1")
    assert described is not None
    channels = described["channels"]
    assert isinstance(channels, list) and len(channels) == 2
    assert [ch["label"] for ch in channels] == ["Ops Alerts", "Daily Digest"]
    assert all(ch["enabled"] is True for ch in channels)

    # Select only the first channel and delivery targets without firing a provider call.
    called_urls.clear()
    first_id = str(channels[0]["channel_id"])
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="select-single-1",
            webhook_url="",
            selected_channel_ids=(first_id,),
            delivery_targets=("teams-a2-operational-alert",),
            selection_only=True,
        )
    )
    assert called_urls == []
    after_single = await tester.describe_binding(actor_id="owner-1")
    assert after_single is not None
    single_channels = after_single["channels"]
    assert isinstance(single_channels, list)
    assert [ch["enabled"] for ch in single_channels] == [True, False]
    assert after_single["delivery_targets"] == ["teams-a2-operational-alert"]


async def test_per_actor_email_rename_single_channel_test_and_clear() -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    called_urls: list[str] = []

    async def recording_post(url: str, _: object) -> TeamsWorkflowProviderResponse:
        called_urls.append(url)
        return TeamsWorkflowProviderResponse(status_code=202, workflow_run_id="run-ch")

    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=recording_post,
        clock=lambda: NOW,
    )
    second_url = URL.replace(
        "d74f3e0ee1314a4191c650cfda483a70",
        "aaaa3e0ee1314a4191c650cfda483bbb",
    )
    await tester.save_and_test(_command("teams-save-ch1"))
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="teams-save-ch2",
            webhook_url=second_url,
        )
    )

    meta = await tester.describe_binding(actor_id="owner-1")
    assert meta is not None
    channels = meta["channels"]
    assert isinstance(channels, list) and len(channels) == 2
    second_cid = str(channels[1]["channel_id"])

    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="teams-rename-1",
            webhook_url="",
            rename_channel_id=second_cid,
            channel_label="Ops Primary #2",
            email_recipient_mode="custom",
            custom_email="owner1@example.com",
            selection_only=True,
        )
    )
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-2",
            request_id="teams-email-2",
            webhook_url="",
            email_recipient_mode="custom",
            custom_email="owner2@example.com",
            selection_only=True,
        )
    )

    meta_owner1 = await tester.describe_binding(actor_id="owner-1")
    meta_owner2 = await tester.describe_binding(actor_id="owner-2")
    assert meta_owner1 is not None and meta_owner1["custom_email"] == "owner1@example.com"
    assert meta_owner2 is not None and meta_owner2["custom_email"] == "owner2@example.com"

    called_urls.clear()
    await tester.save_and_test(
        TeamsWorkflowTestCommand(
            actor_id="owner-1",
            request_id="teams-test-single-ch2",
            webhook_url="",
            test_channel_id=second_cid,
        )
    )
    assert called_urls == [second_url]
    after_test = await tester.describe_binding(actor_id="owner-1")
    assert after_test is not None
    ch_after = after_test["channels"]
    assert isinstance(ch_after, list)
    assert ch_after[1]["label"] == "Ops Primary #2"
    assert ch_after[1]["last_test_status"] == 202
    assert ch_after[1]["last_test_accepted"] is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"channel_label": "Bad\nLabel"},
        {"selected_channel_ids": ("../bad",), "webhook_url": "", "selection_only": True},
        {"delivery_targets": ("unknown-target",), "webhook_url": "", "selection_only": True},
        {
            "email_recipient_mode": "custom",
            "custom_email": "",
            "webhook_url": "",
            "selection_only": True,
        },
        {
            "email_recipient_mode": "custom",
            "custom_email": "bad\r\n@example.com",
            "webhook_url": "",
            "selection_only": True,
        },
        {"remove_channel_id": "ch-nonexistent12", "webhook_url": "", "selection_only": True},
    ],
)
async def test_hardened_channel_and_email_boundaries_reject_invalid_inputs(
    kwargs: dict[str, object],
) -> None:
    store = MemoryStore()
    bindings = MemoryBindingStore()
    tester = TeamsWorkflowDiagnosticTester(
        store=store,
        binding_store=bindings,
        post=_accepting_post(),
        clock=lambda: NOW,
    )
    await tester.save_and_test(_command("teams-save-initial"))

    base: dict[str, object] = {
        "actor_id": "owner-1",
        "request_id": "teams-invalid-1",
        "webhook_url": URL,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        await tester.save_and_test(TeamsWorkflowTestCommand(**base))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="channel_id is invalid"):
        await tester.reveal_binding(actor_id="owner-1", channel_id="../bad")


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
