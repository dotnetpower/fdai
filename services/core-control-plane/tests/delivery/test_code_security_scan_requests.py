"""Tests for code-security repository registration and Console scan-request processing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest
from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import SourceAcquisitionError
from fdai.delivery.code_security_repo_cli import github_auth_header
from fdai.delivery.code_security_repository_changes import (
    REJECT_REPOSITORY_CONFLICT,
    REPOSITORY_CHANGE_OPERATION,
    parse_repository_change,
)
from fdai.delivery.code_security_revision_state import read_successful_revision
from fdai.delivery.code_security_scan_requests import (
    REJECT_ATTEMPTS,
    REJECT_CONFLICT,
    REJECT_DISABLED,
    REJECT_MALFORMED,
    REJECT_ROLE,
    REJECT_SOURCE,
    REJECT_UNREGISTERED,
    SCAN_REQUEST_OPERATION,
    ClaimedScanRequest,
    ScanOutcome,
    parse_scan_request,
    process_scan_requests,
)
from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    CodeSecurityRepositoryError,
    clone_url,
    list_repositories,
    read_repository,
    register_repository,
    set_repository_enabled,
)
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
)
from fdai.rule_catalog.code_security import Exposure
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REQUEST_ID = "operator-" + "c" * 32
_REVISION = "d" * 40


async def test_registration_is_idempotent_audited_and_never_repointed() -> None:
    store = InMemoryStateStore()
    repository, created = await register_repository(
        store, alias="example-app", location="example/app", registered_by="owner@example.com"
    )
    assert created and repository.enabled and repository.revision == 1
    again, created = await register_repository(
        store, alias="example-app", location="example/app", registered_by="someone-else"
    )
    assert not created and again.registered_by == "owner@example.com"
    with pytest.raises(CodeSecurityRepositoryError, match="another location"):
        await register_repository(
            store, alias="example-app", location="example/other", registered_by="x"
        )
    audit = [item["entry"] for item in store.audit_entries]
    assert [entry["change"] for entry in audit] == ["registered"]
    assert audit[0]["producer_principal"] == "Heimdall"
    assert audit[0]["execution_authority"] is False


@pytest.mark.parametrize(
    ("alias", "location", "ref"),
    [
        ("bad alias", "example/app", "main"),
        ("ok", "https://github.com/example/app", "main"),
        ("ok", "example/app/extra", "main"),
        ("ok", "example/app", "../main"),
    ],
)
async def test_registration_rejects_malformed_input(alias: str, location: str, ref: str) -> None:
    with pytest.raises(CodeSecurityRepositoryError):
        await register_repository(
            InMemoryStateStore(),
            alias=alias,
            location=location,
            default_ref=ref,
            registered_by="owner",
        )


async def test_enable_and_disable_use_compare_and_set_with_audit() -> None:
    store = InMemoryStateStore()
    await register_repository(
        store,
        alias="b-app",
        location="example/b",
        exposure=Exposure.EXPOSED,
        registered_by="owner",
    )
    await register_repository(store, alias="a-app", location="example/a", registered_by="owner")
    disabled = await set_repository_enabled(store, "b-app", enabled=False, actor="owner")
    assert (disabled.enabled, disabled.revision, disabled.exposure) == (False, 2, "exposed")
    assert (
        await set_repository_enabled(store, "b-app", enabled=False, actor="owner")
    ).revision == 2
    assert [r.repository_alias for r in await list_repositories(store)] == ["a-app", "b-app"]
    assert [item["entry"]["change"] for item in store.audit_entries][-1] == "disabled"
    with pytest.raises(CodeSecurityRepositoryError, match="not registered"):
        await set_repository_enabled(store, "missing", enabled=True, actor="owner")


def test_clone_url_is_credential_free_https() -> None:
    repository = CodeSecurityRepository(
        repository_alias="a",
        provider="github",
        location="example/app",
        default_ref="main",
        exposure="unknown",
        enabled=True,
        registered_at="2026-10-08T00:00:00+00:00",
        registered_by="owner",
        revision=1,
    )
    assert clone_url(repository) == "https://github.com/example/app.git"
    assert (
        clone_url(repository, "https://ghe.example.com/")
        == "https://ghe.example.com/example/app.git"
    )
    for bad in ("http://github.com", "https://token@github.com"):
        with pytest.raises(CodeSecurityRepositoryError):
            clone_url(repository, bad)


def _record(body: Mapping[str, object], roles: tuple[str, ...] = ("Contributor",)) -> dict:  # type: ignore[type-arg]
    return {
        "operation": SCAN_REQUEST_OPERATION,
        "proposal_id": _REQUEST_ID,
        "payload": {"payload": dict(body), "principal_roles": list(roles)},
    }


def test_parse_scan_request_accepts_only_the_typed_body() -> None:
    request = parse_scan_request(_record({"repository_alias": "example-app", "ref": "v1.2"}))
    assert request is not None and (request.repository_alias, request.ref) == (
        "example-app",
        "v1.2",
    )
    assert parse_scan_request(_record({"repository_alias": "example-app"})) is not None
    for body in (
        {"repository_alias": "example-app", "location": "evil/repo"},
        {"repository_alias": "../x"},
        {"repository_alias": "example-app", "ref": "--upload-pack=x"},
        {"repository_alias": "example-app", "ref": 3},
    ):
        assert parse_scan_request(_record(body)) is None
    assert parse_scan_request({**_record({"repository_alias": "a"}), "operation": "x"}) is None
    assert parse_scan_request({**_record({"repository_alias": "a"}), "proposal_id": "x"}) is None


@dataclass
class _Queue:
    claims: list[ClaimedScanRequest]
    completed: list[tuple[str, Mapping[str, object]]] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    async def claim(self) -> ClaimedScanRequest | None:
        return self.claims.pop(0) if self.claims else None

    async def renew(self, *, key: str, claim_id: str) -> bool:
        return True

    async def mark_completed(
        self, *, key: str, claim_id: str, result: Mapping[str, object]
    ) -> bool:
        self.completed.append((key, result))
        return True

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool:
        self.rejected.append((key, reason_code))
        return True


def _claim(body: Mapping[str, object], *, roles=("Contributor",), attempt: int = 1):  # type: ignore[no-untyped-def]
    return ClaimedScanRequest(
        key=f"operator-proposal:operations:{len(body)}",
        claim_id="claim",
        request=parse_scan_request(_record(body, roles)),
        attempt=attempt,
    )


def _package(source: ReviewSource) -> dict[str, object]:
    return {
        "revision": _REVISION,
        "review_digest": "e" * 64,
        "issue_count": 1,
        "coverage_complete": True,
        "by_priority": {"P0": 1, "P1": 0, "P2": 0, "P3": 0, "P4": 0},
        "source": source.as_dict(),
    }


class _Publisher:
    def __init__(self) -> None:
        self.packages: list[Mapping[str, object]] = []

    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool:
        self.packages.append(package)
        return True


async def test_processor_scans_enabled_registration_and_closes_the_request() -> None:
    store = InMemoryStateStore()
    await register_repository(
        store, alias="example-app", location="example/app", default_ref="main", registered_by="o"
    )
    calls: list[tuple[str, ReviewSource]] = []
    recorded: list[Mapping[str, object]] = []

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource):  # type: ignore[no-untyped-def]
        calls.append((ref, source))
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        recorded.append(outcome.package)
        return True

    queue = _Queue([_claim({"repository_alias": "example-app"})])
    publisher = _Publisher()
    (outcome,) = await process_scan_requests(
        queue, store, runner, recorder=recorder, publisher=publisher, max_requests=5
    )
    ((ref, source),) = calls
    assert ref == "main"
    assert (source.kind, source.provider, source.trigger) == ("git_repository", "github", "console")
    assert source.request_id == _REQUEST_ID
    assert outcome["status"] == "published" and outcome["decision"] == "urgent"
    assert recorded and publisher.packages == recorded
    assert await read_successful_revision(store, "example-app") == _REVISION
    ((_, result),) = queue.completed
    assert result == {
        "revision": _REVISION,
        "review_digest": "e" * 64,
        "decision": "urgent",
        "issue_count": 1,
        "coverage_complete": True,
        "published": True,
    }


async def test_processor_rejects_every_unsafe_or_failed_request() -> None:
    store = InMemoryStateStore()
    await register_repository(store, alias="on", location="example/on", registered_by="o")
    await register_repository(store, alias="off", location="example/off", registered_by="o")
    await set_repository_enabled(store, "off", enabled=False, actor="o")
    await register_repository(store, alias="broken", location="example/broken", registered_by="o")
    await register_repository(store, alias="taken", location="example/taken", registered_by="o")

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource):  # type: ignore[no-untyped-def]
        if repo.repository_alias == "broken":
            raise SourceAcquisitionError("ref did not resolve")
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        raise CodeSecurityReviewConflictError("different findings")

    malformed = ClaimedScanRequest(key="k0", claim_id="c", request=None)
    queue = _Queue(
        [
            malformed,
            _claim({"repository_alias": "on"}, roles=("Reader",)),
            _claim({"repository_alias": "missing"}),
            _claim({"repository_alias": "off"}),
            _claim({"repository_alias": "broken"}),
            _claim({"repository_alias": "taken"}),
            _claim({"repository_alias": "on"}, attempt=4),
        ]
    )
    outcomes = await process_scan_requests(queue, store, runner, recorder=recorder, max_requests=10)
    assert [item["reason_code"] for item in outcomes] == [
        REJECT_MALFORMED,
        REJECT_ROLE,
        REJECT_UNREGISTERED,
        REJECT_DISABLED,
        REJECT_SOURCE,
        REJECT_CONFLICT,
        REJECT_ATTEMPTS,
    ]
    assert not queue.completed and len(queue.rejected) == 7


async def test_processor_bounds_its_batch() -> None:
    with pytest.raises(ValueError, match="max_requests"):
        await process_scan_requests(
            _Queue([]),
            InMemoryStateStore(),
            None,
            recorder=None,
            max_requests=0,  # type: ignore[arg-type]
        )


async def test_github_auth_header_uses_only_configured_credentials() -> None:
    assert await github_auth_header("example/app", {}) is None
    header = await github_auth_header("example/app", {"FDAI_GITOPS_TOKEN": "t0ken"})
    assert header == "Basic eC1hY2Nlc3MtdG9rZW46dDBrZW4="


async def test_read_repository_rejects_bad_alias() -> None:
    with pytest.raises(CodeSecurityRepositoryError):
        await read_repository(InMemoryStateStore(), "../x")


def _change_record(body: Mapping[str, object], roles: tuple[str, ...] = ("Owner",)) -> dict:  # type: ignore[type-arg]
    return {
        "operation": REPOSITORY_CHANGE_OPERATION,
        "proposal_id": "operator-" + "f" * 32,
        "principal_id": "owner-oid",
        "payload": {"payload": dict(body), "principal_roles": list(roles)},
    }


def test_parse_repository_change_accepts_only_typed_actions() -> None:
    register = parse_repository_change(
        _change_record(
            {
                "action": "register",
                "repository_alias": "example-app",
                "location": "example/app",
                "default_ref": "release/1",
                "exposure": "exposed",
            }
        )
    )
    assert register is not None and register.location == "example/app"
    assert register.exposure == "exposed" and register.principal_id == "owner-oid"
    toggle = parse_repository_change(
        _change_record({"action": "disable", "repository_alias": "example-app"})
    )
    assert toggle is not None and toggle.action == "disable" and toggle.location is None
    for body in (
        {"action": "delete", "repository_alias": "example-app"},
        {"action": "register", "repository_alias": "example-app"},
        {"action": "register", "repository_alias": "a", "location": "https://evil/x"},
        {"action": "register", "repository_alias": "a", "location": "o/r", "default_ref": "../x"},
        {"action": "register", "repository_alias": "a", "location": "o/r", "exposure": "public"},
        {"action": "enable", "repository_alias": "a", "location": "o/r"},
    ):
        assert parse_repository_change(_change_record(body)) is None, body


async def test_processor_applies_owner_changes_before_scans_and_audits_the_requester() -> None:
    store = InMemoryStateStore()

    def claim(body: Mapping[str, object], roles=("Owner",)):  # type: ignore[no-untyped-def]
        record = _change_record(body, roles)
        return ClaimedScanRequest(
            key=f"k-{len(body)}-{body['action']}",
            claim_id="c",
            request=None,
            operation=REPOSITORY_CHANGE_OPERATION,
            change=parse_repository_change(record),
        )

    register = {"action": "register", "repository_alias": "example-app", "location": "example/app"}
    queue = _Queue(
        [
            claim(register),
            claim(register | {"location": "example/other"}),
            claim({"action": "disable", "repository_alias": "example-app"}),
            claim({"action": "enable", "repository_alias": "missing"}),
            claim({"action": "enable", "repository_alias": "example-app"}, roles=("Contributor",)),
            ClaimedScanRequest(
                key="bad", claim_id="c", request=None, operation=REPOSITORY_CHANGE_OPERATION
            ),
        ]
    )

    scan_calls: list[tuple[str, ReviewSource]] = []

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource) -> ScanOutcome:
        scan_calls.append((ref, source))
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        return True

    outcomes = await process_scan_requests(queue, store, runner, recorder=recorder, max_requests=10)
    assert [item["status"] for item in outcomes] == [
        "published",
        "rejected",
        "published",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert [item.get("reason_code") for item in outcomes if item["status"] == "rejected"] == [
        REJECT_REPOSITORY_CONFLICT,
        REJECT_UNREGISTERED,
        REJECT_ROLE,
        REJECT_MALFORMED,
    ]
    repository = await read_repository(store, "example-app")
    assert repository is not None and repository.enabled is False
    assert repository.registered_by == "owner-oid"
    actors = [item["entry"]["actor"] for item in store.audit_entries]
    assert actors == ["owner-oid", "owner-oid"]
    assert len(scan_calls) == 1
    assert scan_calls[0][0] == "HEAD"
    assert scan_calls[0][1].request_id == "operator-" + "f" * 32
    assert queue.completed[0][1] == {
        "action": "register",
        "repository_alias": "example-app",
        "enabled": True,
        "created": True,
        "initial_scan": {
            "status": "completed",
            "revision": _REVISION,
            "review_digest": "e" * 64,
            "decision": "urgent",
            "issue_count": 1,
            "coverage_complete": True,
            "published": False,
        },
    }
    assert await read_successful_revision(store, "example-app") == _REVISION


async def test_registration_survives_an_explicit_initial_scan_failure() -> None:
    store = InMemoryStateStore()
    change = parse_repository_change(
        _change_record(
            {
                "action": "register",
                "repository_alias": "example-app",
                "location": "example/app",
            }
        )
    )
    assert change is not None
    queue = _Queue(
        [
            ClaimedScanRequest(
                key="register",
                claim_id="claim",
                request=None,
                operation=REPOSITORY_CHANGE_OPERATION,
                change=change,
            )
        ]
    )

    async def runner(*_args):  # type: ignore[no-untyped-def]
        raise SourceAcquisitionError("repository unavailable")

    (outcome,) = await process_scan_requests(
        queue,
        store,
        runner,
        recorder=None,  # type: ignore[arg-type]
    )
    assert outcome["status"] == "published"
    assert await read_repository(store, "example-app") is not None
    assert queue.completed[0][1]["initial_scan"] == {
        "status": "failed",
        "reason_code": REJECT_SOURCE,
    }


async def test_registration_without_a_ref_follows_the_default_branch() -> None:
    store = InMemoryStateStore()
    repository, _ = await register_repository(
        store, alias="example-app", location="example/app", registered_by="owner"
    )
    assert repository.default_ref == "HEAD"
    change = parse_repository_change(
        _change_record({"action": "register", "repository_alias": "b", "location": "example/b"})
    )
    assert change is not None and change.default_ref == "HEAD"
