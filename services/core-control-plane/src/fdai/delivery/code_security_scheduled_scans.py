"""Scheduled code-security scans of every enabled registered repository.

A deployment runs this bounded batch on a schedule. It lists the enabled registrations in alias
order, resolves each default ref to an exact commit through the same scan runner as the Console
request worker, and records each review with ``trigger: schedule``. Heimdall publishes the review
on ``object.drift`` when a bus is bound.

Each repository ends in exactly one outcome: ``published`` with the bounded result summary,
``failed`` with a reason code, or ``deferred`` when the batch is full. One repository's failure
never stops the others, and a deferred repository is named so the schedule's capacity gap is
visible. A scan never writes to the repository and never grants approval or execution authority.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import SourceAcquisitionError
from fdai.delivery.code_security_scan_requests import (
    REJECT_CONFLICT,
    REJECT_SCAN,
    REJECT_SOURCE,
    ReviewPublisher,
    ReviewRecorder,
    ScanRunner,
    scan_result_summary,
)
from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    list_repositories,
)
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
)
from fdai.shared.providers.state_store import StateStore

SCHEDULE_TRIGGER = "schedule"
DEFERRED_CAPACITY = "schedule_capacity"
MAX_SCHEDULED_REPOSITORIES = 20


async def process_scheduled_scans(
    store: StateStore,
    runner: ScanRunner,
    *,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None = None,
    max_repositories: int = 5,
) -> Sequence[dict[str, object]]:
    """Scan up to ``max_repositories`` enabled registrations and return one outcome for each."""
    if not 1 <= max_repositories <= MAX_SCHEDULED_REPOSITORIES:
        raise ValueError(f"max_repositories MUST be in [1, {MAX_SCHEDULED_REPOSITORIES}]")
    enabled = [item for item in await list_repositories(store) if item.enabled]
    outcomes: list[dict[str, object]] = []
    for repository in enabled[:max_repositories]:
        outcomes.append(await _scan(repository, runner, recorder, publisher))
    outcomes.extend(
        {
            "repository_alias": repository.repository_alias,
            "status": "deferred",
            "reason_code": DEFERRED_CAPACITY,
        }
        for repository in enabled[max_repositories:]
    )
    return outcomes


async def _scan(
    repository: CodeSecurityRepository,
    runner: ScanRunner,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None,
) -> dict[str, object]:
    alias = repository.repository_alias
    source = ReviewSource(
        kind="git_repository", provider=repository.provider, trigger=SCHEDULE_TRIGGER
    )
    try:
        outcome = await runner(repository, repository.default_ref, source)
    except SourceAcquisitionError:
        return {"repository_alias": alias, "status": "failed", "reason_code": REJECT_SOURCE}
    except (OSError, ValueError):
        return {"repository_alias": alias, "status": "failed", "reason_code": REJECT_SCAN}
    try:
        await recorder(outcome)
    except CodeSecurityReviewConflictError:
        return {"repository_alias": alias, "status": "failed", "reason_code": REJECT_CONFLICT}
    package = outcome.package
    published = await publisher.publish_code_security_drift(package) if publisher else False
    return {
        "repository_alias": alias,
        "status": "published",
        **scan_result_summary(package),
        "published": published,
    }


__all__ = [
    "DEFERRED_CAPACITY",
    "MAX_SCHEDULED_REPOSITORIES",
    "SCHEDULE_TRIGGER",
    "process_scheduled_scans",
]
