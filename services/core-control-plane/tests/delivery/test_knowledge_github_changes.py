from __future__ import annotations

import pytest
from fdai.delivery.code_security_repository_changes import (
    apply_repository_change,
    parse_repository_change,
)
from fdai.delivery.code_security_scan_requests import (
    REJECT_DISABLED,
    ClaimedScanRequest,
    parse_scan_request,
    process_scan_requests,
)
from fdai.delivery.persistence.state_store_code_security_repository import (
    read_repository,
    set_repository_enabled,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_github_app_auth.repository_reader import (
    GitHubRepositoryObservation,
    GitHubRepositoryReadError,
)

REQUEST = "operator-" + "c" * 32


class Reader:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def verify(self, location, credential_reference):
        self.calls.append((location, credential_reference))
        if self.fail:
            raise GitHubRepositoryReadError("unavailable")
        return GitHubRepositoryObservation(123, False, "main", "a" * 40, "b" * 64)


def proposal(*, roles=("Owner",), action="connect", revision=0, request=REQUEST, **extra):
    body = {"action": action, "repository_alias": "example-app", "expected_revision": revision}
    if action == "connect":
        body.update(location="example/app", credential_reference="public")
    body.update(extra)
    return {
        "operation": "code_security.repository_change",
        "proposal_id": request,
        "principal_id": "owner",
        "payload": {"payload": body, "principal_roles": list(roles)},
    }


async def apply(store, record, reader):
    change = parse_repository_change(record)
    assert change is not None
    return await apply_repository_change(store, change, knowledge_reader=reader)


async def test_real_connection_is_persisted_but_scan_permission_is_not_granted() -> None:
    store, reader = InMemoryStateStore(), Reader()
    result, reason = await apply(store, proposal(), reader)
    assert reason is None and result["enabled"] is False
    repository = await read_repository(store, "example-app")
    assert repository.knowledge_source.knowledge_read_enabled
    assert repository.knowledge_source.credential_reference == "public"
    assert repository.knowledge_source.observed_commit == "a" * 40
    assert not repository.enabled
    assert store.audit_entries[0]["entry"]["producer_principal"] == "Heimdall"
    assert store.audit_entries[0]["entry"]["execution_authority"] is False
    assert store.audit_entries[0]["entry"]["change"] == "knowledge_connected"
    # Knowledge consent does not change the existing scan-request authorization contract.
    scan = parse_scan_request(
        {
            "operation": "code_security.scan_request",
            "proposal_id": "operator-" + "d" * 32,
            "principal_id": "owner",
            "payload": {
                "payload": {"repository_alias": "example-app"},
                "principal_roles": ["Owner"],
            },
        }
    )
    assert scan is not None and REJECT_DISABLED == "repository_disabled"
    again, reason = await apply(store, proposal(), reader)
    assert again == result and reason is None and len(reader.calls) == 1
    assert len(store.audit_entries) == 1


@pytest.mark.parametrize("roles", [("Reader",), ("Contributor",), ("Approver",), ()])
async def test_unauthorized_request_cannot_read_provider_or_change_state(roles) -> None:
    store, reader = InMemoryStateStore(), Reader()
    result, reason = await apply(store, proposal(roles=roles), reader)
    assert result is None and reason == "requester_role_insufficient"
    assert reader.calls == [] and not store.audit_entries


@pytest.mark.parametrize(
    "extra",
    [
        {"enabled": True},
        {"scan_enabled": True},
        {"token": "not-allowed"},
        {"credential_reference": "raw-key"},
        {"expected_revision": True},
        {"location": "example/.."},
        {"principal_roles": ["Owner"]},
    ],
)
def test_malformed_or_authority_fields_are_refused(extra) -> None:
    assert parse_repository_change(proposal(**extra)) is None


async def test_failed_validation_and_conflict_leave_previous_evidence_unchanged() -> None:
    store = InMemoryStateStore()
    await apply(store, proposal(), Reader())
    before = await read_repository(store, "example-app")
    failed = await apply(store, proposal(revision=1, request="operator-" + "d" * 32), Reader(True))
    assert failed == (None, "source_unavailable")
    stale_reader = Reader()
    assert await apply(store, proposal(request="operator-" + "e" * 32), stale_reader) == (
        None,
        "repository_conflict",
    )
    assert stale_reader.calls == []
    assert await read_repository(store, "example-app") == before
    assert len(store.audit_entries) == 1


async def test_separate_owner_scan_enable_and_knowledge_disconnect_are_independent() -> None:
    store = InMemoryStateStore()
    await apply(store, proposal(), Reader())
    record = {
        "operation": "code_security.repository_change",
        "proposal_id": "operator-" + "d" * 32,
        "principal_id": "owner",
        "payload": {
            "payload": {"action": "enable", "repository_alias": "example-app"},
            "principal_roles": ["Owner"],
        },
    }
    change = parse_repository_change(record)
    result, reason = await apply_repository_change(store, change)
    assert result["enabled"] is True and reason is None
    assert await read_repository(store, "example-app") is not None
    disconnected, reason = await apply(
        store,
        proposal(
            action="disconnect",
            revision=2,
            request="operator-" + "e" * 32,
        ),
        Reader(),
    )
    assert reason is None and disconnected["enabled"] is True
    repository = await read_repository(store, "example-app")
    assert repository.enabled and not repository.knowledge_source.knowledge_read_enabled
    assert repository.revision == 3


async def test_reconnecting_preserves_existing_scan_permission_and_rejects_repoint() -> None:
    store = InMemoryStateStore()
    await apply(store, proposal(), Reader())
    await set_repository_enabled(store, "example-app", enabled=True, actor="owner")
    result, reason = await apply(
        store, proposal(revision=2, request="operator-" + "d" * 32), Reader()
    )
    assert reason is None and result["enabled"] is True
    reader = Reader()
    assert await apply(
        store,
        proposal(
            revision=3,
            request="operator-" + "e" * 32,
            location="example/other",
        ),
        reader,
    ) == (None, "repository_conflict")
    assert reader.calls == []


async def test_worker_connect_then_scan_rejects_knowledge_read_as_scan_consent(monkeypatch) -> None:
    from fdai_github_app_auth.repository_reader import GitHubApiRepositoryReader

    store = InMemoryStateStore()
    observations = []

    async def verify(self, location, credential_reference):
        observations.append((location, credential_reference))
        return GitHubRepositoryObservation(123, False, "main", "a" * 40, "b" * 64)

    monkeypatch.setattr(GitHubApiRepositoryReader, "verify", verify)
    scan = parse_scan_request(
        {
            "operation": "code_security.scan_request",
            "proposal_id": "operator-" + "d" * 32,
            "principal_id": "owner",
            "payload": {
                "payload": {"repository_alias": "example-app"},
                "principal_roles": ["Owner"],
            },
        }
    )

    class Queue:
        def __init__(self):
            self.claims = [
                ClaimedScanRequest(
                    "connection",
                    "first",
                    None,
                    operation="code_security.repository_change",
                    change=parse_repository_change(proposal()),
                ),
                ClaimedScanRequest("scan", "second", scan),
            ]
            self.rejected = []
            self.completed = []

        async def claim(self):
            return self.claims.pop(0) if self.claims else None

        async def mark_rejected(self, *, key, claim_id, reason_code):
            self.rejected.append(reason_code)
            return True

        async def mark_completed(self, *, key, claim_id, result):
            self.completed.append(result)
            return True

    async def forbidden(*args):
        pytest.fail("Knowledge read alone must not run, record, or publish a scan")

    queue = Queue()
    await process_scan_requests(queue, store, forbidden, recorder=forbidden, max_requests=2)
    assert observations == [("example/app", "public")]
    assert len(queue.completed) == 1 and queue.completed[0]["enabled"] is False
    assert queue.rejected == [REJECT_DISABLED]


async def test_read_validation_does_not_overwrite_concurrent_scan_permission_change() -> None:
    store = InMemoryStateStore()
    await apply(store, proposal(), Reader())

    class ConcurrentReader(Reader):
        async def verify(self, location, credential_reference):
            await set_repository_enabled(store, "example-app", enabled=True, actor="other-owner")
            return await super().verify(location, credential_reference)

    result, reason = await apply(
        store,
        proposal(revision=1, request="operator-" + "d" * 32),
        ConcurrentReader(),
    )
    assert result is None and reason == "repository_conflict"
    repository = await read_repository(store, "example-app")
    assert repository.enabled and repository.revision == 2
    assert repository.knowledge_source.request_id == REQUEST
