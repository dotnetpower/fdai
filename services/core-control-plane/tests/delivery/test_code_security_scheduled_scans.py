"""Tests for the scheduled code-security scan of enabled registered repositories."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

import pytest
from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import SourceAcquisitionError
from fdai.delivery.code_security_cli import _parser
from fdai.delivery.code_security_scan_requests import (
    REJECT_CONFLICT,
    REJECT_SCAN,
    REJECT_SOURCE,
    ScanOutcome,
)
from fdai.delivery.code_security_scheduled_scans import (
    DEFERRED_CAPACITY,
    SCHEDULE_CURSOR_KEY,
    process_scheduled_scans,
)
from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    register_repository,
    set_repository_enabled,
)
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_REVISION = "d" * 40


def _package(source: ReviewSource) -> dict[str, object]:
    return {
        "revision": _REVISION,
        "review_digest": "e" * 64,
        "issue_count": 0,
        "coverage_complete": True,
        "by_priority": {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0},
        "source": source.as_dict(),
    }


class _Publisher:
    def __init__(self) -> None:
        self.packages: list[Mapping[str, object]] = []

    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool:
        self.packages.append(package)
        return True


async def _register(store: InMemoryStateStore, *aliases: str) -> None:
    for alias in aliases:
        await register_repository(
            store, alias=alias, location=f"example/{alias}", default_ref="main", registered_by="o"
        )


async def test_schedule_scans_enabled_repositories_with_the_schedule_trigger() -> None:
    store = InMemoryStateStore()
    await _register(store, "b-app", "a-app", "off-app")
    await set_repository_enabled(store, "off-app", enabled=False, actor="o")
    calls: list[tuple[str, str, ReviewSource]] = []
    recorded: list[Mapping[str, object]] = []

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource):  # type: ignore[no-untyped-def]
        calls.append((repo.repository_alias, ref, source))
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        recorded.append(outcome.package)
        return True

    publisher = _Publisher()
    outcomes = await process_scheduled_scans(
        store, runner, recorder=recorder, publisher=publisher, max_repositories=5
    )
    assert [alias for alias, _, _ in calls] == ["a-app", "b-app"]
    for _, ref, source in calls:
        assert ref == "main"
        assert (source.kind, source.provider, source.trigger) == (
            "git_repository",
            "github",
            "schedule",
        )
        assert source.request_id is None
    assert [item["status"] for item in outcomes] == ["published", "published"]
    assert outcomes[0] == {
        "repository_alias": "a-app",
        "status": "published",
        "revision": _REVISION,
        "review_digest": "e" * 64,
        "decision": "clear",
        "issue_count": 0,
        "coverage_complete": True,
        "published": True,
    }
    assert publisher.packages == recorded


async def test_schedule_isolates_failures_and_names_deferred_repositories() -> None:
    store = InMemoryStateStore()
    await _register(store, "a-source", "b-scan", "c-conflict", "d-ok", "e-later", "f-later")

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource):  # type: ignore[no-untyped-def]
        if repo.repository_alias == "a-source":
            raise SourceAcquisitionError("ref did not resolve")
        if repo.repository_alias == "b-scan":
            raise OSError("scanner crashed")
        return ScanOutcome(_package(source))

    conflicts = ["c-conflict"]

    async def recorder(outcome: ScanOutcome) -> bool:
        if conflicts:
            conflicts.pop()
            raise CodeSecurityReviewConflictError("different findings")
        return True

    outcomes = await process_scheduled_scans(store, runner, recorder=recorder, max_repositories=4)
    assert [
        (item["repository_alias"], item["status"], item.get("reason_code")) for item in outcomes
    ] == [
        ("a-source", "failed", REJECT_SOURCE),
        ("b-scan", "failed", REJECT_SCAN),
        ("c-conflict", "failed", REJECT_CONFLICT),
        ("d-ok", "published", None),
        ("e-later", "deferred", DEFERRED_CAPACITY),
        ("f-later", "deferred", DEFERRED_CAPACITY),
    ]
    assert outcomes[3]["published"] is False


@pytest.mark.parametrize("bound", [0, 21])
async def test_schedule_bounds_its_batch(bound: int) -> None:
    with pytest.raises(ValueError, match="max_repositories"):
        await process_scheduled_scans(
            InMemoryStateStore(),
            None,  # type: ignore[arg-type]
            recorder=None,  # type: ignore[arg-type]
            max_repositories=bound,
        )


async def test_schedule_with_no_enabled_repository_does_nothing() -> None:
    assert await process_scheduled_scans(InMemoryStateStore(), None, recorder=None) == []  # type: ignore[arg-type]


def test_cli_parses_the_scheduled_worker() -> None:
    args = _parser().parse_args(
        ["process-scheduled-scans", "--max-repositories", "3", "--scanner-bin", "opengrep=/x"]
    )
    assert isinstance(args, argparse.Namespace)
    assert (args.command, args.max_repositories, args.scanner_bin) == (
        "process-scheduled-scans",
        3,
        ["opengrep=/x"],
    )


async def test_bounded_schedule_rotates_past_failed_and_deferred_repositories() -> None:
    store = InMemoryStateStore()
    await _register(store, "a-app", "b-app", "c-app")
    calls: list[str] = []

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource) -> ScanOutcome:
        calls.append(repo.repository_alias)
        if repo.repository_alias == "a-app":
            raise SourceAcquisitionError("not available")
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        return True

    for _ in range(4):
        outcomes = await process_scheduled_scans(
            store, runner, recorder=recorder, max_repositories=1
        )
        assert sum(item["status"] == "deferred" for item in outcomes) == 2
    assert calls == ["a-app", "b-app", "c-app", "a-app"]
    assert await store.read_state(SCHEDULE_CURSOR_KEY) == {"last_repository_alias": "a-app"}


async def test_schedule_cursor_survives_disabled_repository() -> None:
    store = InMemoryStateStore()
    await _register(store, "a-app", "b-app", "c-app")
    await store.write_state(SCHEDULE_CURSOR_KEY, {"last_repository_alias": "b-app"})
    await set_repository_enabled(store, "b-app", enabled=False, actor="o")

    async def runner(repo: CodeSecurityRepository, ref: str, source: ReviewSource) -> ScanOutcome:
        return ScanOutcome(_package(source))

    async def recorder(outcome: ScanOutcome) -> bool:
        return True

    outcomes = await process_scheduled_scans(store, runner, recorder=recorder, max_repositories=1)
    assert outcomes[0]["repository_alias"] == "c-app"


@pytest.mark.parametrize(
    "cursor",
    [
        {},
        {"last_repository_alias": 42},
        {
            "last_repository_alias": "valid",
            "unexpected": True,
        },
    ],
)
async def test_malformed_schedule_cursor_is_not_silently_reset(
    cursor: dict[str, object],
) -> None:
    store = InMemoryStateStore()
    await store.write_state(SCHEDULE_CURSOR_KEY, cursor)
    with pytest.raises(ValueError, match="cursor is malformed"):
        await process_scheduled_scans(
            store,
            None,
            recorder=None,  # type: ignore[arg-type]
        )
