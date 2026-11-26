"""Process Console code-security scan requests and registration changes.

The Console submits a scan request as a typed Operator proposal (``code_security.scan_request``).
This worker claims one pending proposal at a time, checks that the alias names an enabled
registration, resolves the requested ref to an exact commit, runs the deterministic scan job, and
records the review with ``trigger: console`` and the request id. Heimdall publishes the review on
its ``object.drift`` ownership when a bus is bound, where Forseti judges it and Saga audits it.

Every claim ends in exactly one terminal outcome on the proposal record: ``published`` with a
bounded result summary, or ``rejected`` with a reason code. A scan never writes to the repository
and never grants approval or execution authority.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from fdai.core.security.code_findings.review_signal import ReviewSource, review_decision
from fdai.delivery.code_security_acquire import SourceAcquisitionError
from fdai.delivery.code_security_repository_changes import (
    REPOSITORY_CHANGE_OPERATION,
    RepositoryChange,
    apply_repository_change,
)
from fdai.delivery.code_security_revision_state import record_successful_revision
from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    CodeSecurityRepositoryError,
    read_repository,
    validate_ref,
)
from fdai.delivery.persistence.state_store_code_security_review import (
    CodeSecurityReviewConflictError,
)
from fdai.shared.providers.state_store import StateStore

SCAN_REQUEST_OPERATION = "code_security.scan_request"
REQUESTER_ROLES = frozenset({"Contributor", "Owner"})
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUEST_ID = re.compile(r"^operator-[0-9a-f]{32}$")

REJECT_MALFORMED = "request_malformed"
REJECT_ROLE = "requester_role_insufficient"
REJECT_UNREGISTERED = "repository_not_registered"
REJECT_DISABLED = "repository_disabled"
REJECT_SOURCE = "source_unavailable"
REJECT_SCAN = "scan_failed"
REJECT_CONFLICT = "review_conflict"
REJECT_ATTEMPTS = "attempts_exhausted"
MAX_ATTEMPTS = 3
CLAIM_RENEWAL_SECONDS = 20


class ScanRequestClaimLostError(RuntimeError):
    """A stale worker cannot report a terminal result after its claim was replaced."""


@dataclass(frozen=True, slots=True)
class ScanRequest:
    request_id: str
    repository_alias: str
    ref: str | None
    principal_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimedScanRequest:
    key: str
    claim_id: str
    request: ScanRequest | None
    """``None`` when the proposal body is malformed; the worker rejects it."""
    attempt: int = 1
    operation: str = SCAN_REQUEST_OPERATION
    change: RepositoryChange | None = None
    """The parsed registration change when ``operation`` is a repository change."""


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """The strict review package plus bounded issue summaries for the Console."""

    package: Mapping[str, object]
    issues: Sequence[Mapping[str, object]] = ()
    issues_truncated: bool = False
    artifacts: Mapping[str, str] | None = None


class ScanRequestQueue(Protocol):
    async def claim(self) -> ClaimedScanRequest | None: ...

    async def renew(self, *, key: str, claim_id: str) -> bool: ...

    async def mark_completed(
        self, *, key: str, claim_id: str, result: Mapping[str, object]
    ) -> bool: ...

    async def mark_rejected(self, *, key: str, claim_id: str, reason_code: str) -> bool: ...


ScanRunner = Callable[[CodeSecurityRepository, str, ReviewSource], Awaitable[ScanOutcome]]
"""Scan ``repository`` at ``ref`` and return the review package and issue summaries."""

ReviewRecorder = Callable[[ScanOutcome], Awaitable[bool]]


class ReviewPublisher(Protocol):
    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool: ...


def parse_scan_request(record: Mapping[str, object]) -> ScanRequest | None:
    """Return the typed request from an Operator proposal record, or ``None`` if malformed."""
    if record.get("operation") != SCAN_REQUEST_OPERATION:
        return None
    request_id = record.get("proposal_id")
    envelope = record.get("payload")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        return None
    if not isinstance(envelope, Mapping):
        return None
    body, roles = envelope.get("payload"), envelope.get("principal_roles", ())
    if not isinstance(body, Mapping) or not isinstance(roles, list | tuple):
        return None
    if set(body) - {"repository_alias", "ref"}:
        return None
    alias, ref = body.get("repository_alias"), body.get("ref")
    if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
        return None
    if ref is not None:
        if not isinstance(ref, str):
            return None
        try:
            validate_ref(ref)
        except CodeSecurityRepositoryError:
            return None
    return ScanRequest(
        request_id=request_id,
        repository_alias=alias,
        ref=ref,
        principal_roles=tuple(str(role) for role in roles),
    )


def scan_result_summary(package: Mapping[str, object]) -> dict[str, object]:
    """Return the bounded result the Console shows for a finished request."""
    return {
        "revision": package["revision"],
        "review_digest": package["review_digest"],
        "decision": review_decision(package),
        "issue_count": package["issue_count"],
        "coverage_complete": package["coverage_complete"],
    }


async def process_scan_requests(
    queue: ScanRequestQueue,
    store: StateStore,
    runner: ScanRunner,
    *,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None = None,
    max_requests: int = 1,
) -> Sequence[dict[str, object]]:
    """Process up to ``max_requests`` pending requests and return one outcome per claim."""
    if not 1 <= max_requests <= 20:
        raise ValueError("max_requests MUST be in [1, 20]")
    outcomes: list[dict[str, object]] = []
    for _ in range(max_requests):
        claim = await queue.claim()
        if claim is None:
            break
        outcomes.append(
            await _process_with_renewal(claim, queue, store, runner, recorder, publisher)
        )
    return outcomes


async def _process_with_renewal(
    claim: ClaimedScanRequest,
    queue: ScanRequestQueue,
    store: StateStore,
    runner: ScanRunner,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None,
) -> dict[str, object]:
    async def renew() -> None:
        while True:
            await asyncio.sleep(CLAIM_RENEWAL_SECONDS)
            if not await queue.renew(key=claim.key, claim_id=claim.claim_id):
                raise ScanRequestClaimLostError(
                    "code-security request claim was lost during renewal"
                )

    processing = asyncio.create_task(_process(claim, queue, store, runner, recorder, publisher))
    renewal = asyncio.create_task(renew())
    done, _ = await asyncio.wait({processing, renewal}, return_when=asyncio.FIRST_COMPLETED)
    if renewal in done and not renewal.cancelled() and renewal.exception() is not None:
        processing.cancel()
        try:
            await processing
        except asyncio.CancelledError:
            pass
        renewal.result()
    renewal.cancel()
    try:
        await renewal
    except asyncio.CancelledError:
        pass
    return await processing


async def _reject(
    queue: ScanRequestQueue, claim: ClaimedScanRequest, reason: str
) -> dict[str, object]:
    if not await queue.mark_rejected(key=claim.key, claim_id=claim.claim_id, reason_code=reason):
        raise ScanRequestClaimLostError("code-security request claim was lost before rejection")
    request_id = (
        claim.request.request_id
        if claim.request
        else claim.change.request_id
        if claim.change
        else None
    )
    return {"request_id": request_id, "status": "rejected", "reason_code": reason}


async def _process_change(
    claim: ClaimedScanRequest,
    queue: ScanRequestQueue,
    store: StateStore,
    runner: ScanRunner,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None,
) -> dict[str, object]:
    change = claim.change
    if change is None:
        return await _reject(queue, claim, REJECT_MALFORMED)
    if claim.attempt > MAX_ATTEMPTS:
        return await _reject(queue, claim, REJECT_ATTEMPTS)
    result, reason = await apply_repository_change(store, change)
    if result is None:
        return await _reject(queue, claim, str(reason))
    if change.action in {"register", "enable"} and result.get("enabled") is True:
        repository = await read_repository(store, change.repository_alias)
        if repository is None:
            raise RuntimeError("registered code-security repository was not readable")
        source = ReviewSource(
            kind="git_repository",
            provider=repository.provider,
            trigger="console",
            request_id=change.request_id,
        )
        scan_result, scan_reason = await _run_scan(
            store,
            repository,
            repository.default_ref,
            source,
            runner,
            recorder,
            publisher,
            track_default_revision=True,
        )
        result = {
            **result,
            "initial_scan": (
                {"status": "completed", **scan_result}
                if scan_result is not None
                else {"status": "failed", "reason_code": str(scan_reason)}
            ),
        }
    if not await queue.mark_completed(key=claim.key, claim_id=claim.claim_id, result=result):
        raise ScanRequestClaimLostError("code-security request claim was lost before completion")
    return {"request_id": change.request_id, "status": "published", **result}


async def _run_scan(
    store: StateStore,
    repository: CodeSecurityRepository,
    ref: str,
    source: ReviewSource,
    runner: ScanRunner,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None,
    *,
    track_default_revision: bool,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        outcome = await runner(repository, ref, source)
    except SourceAcquisitionError:
        return None, REJECT_SOURCE
    except (OSError, ValueError):
        return None, REJECT_SCAN
    package = outcome.package
    try:
        await recorder(outcome)
    except CodeSecurityReviewConflictError:
        return None, REJECT_CONFLICT
    published = await publisher.publish_code_security_drift(package) if publisher else False
    result = {**scan_result_summary(package), "published": published}
    if track_default_revision:
        await record_successful_revision(
            store, repository.repository_alias, str(package["revision"])
        )
    return result, None


async def _process(
    claim: ClaimedScanRequest,
    queue: ScanRequestQueue,
    store: StateStore,
    runner: ScanRunner,
    recorder: ReviewRecorder,
    publisher: ReviewPublisher | None,
) -> dict[str, object]:
    if claim.operation == REPOSITORY_CHANGE_OPERATION:
        return await _process_change(claim, queue, store, runner, recorder, publisher)
    request = claim.request
    if request is None:
        return await _reject(queue, claim, REJECT_MALFORMED)
    if claim.attempt > MAX_ATTEMPTS:
        return await _reject(queue, claim, REJECT_ATTEMPTS)
    if not REQUESTER_ROLES & set(request.principal_roles):
        return await _reject(queue, claim, REJECT_ROLE)
    repository = await read_repository(store, request.repository_alias)
    if repository is None:
        return await _reject(queue, claim, REJECT_UNREGISTERED)
    if not repository.enabled:
        return await _reject(queue, claim, REJECT_DISABLED)
    source = ReviewSource(
        kind="git_repository",
        provider=repository.provider,
        trigger="console",
        request_id=request.request_id,
    )
    selected_ref = request.ref or repository.default_ref
    result, reason = await _run_scan(
        store,
        repository,
        selected_ref,
        source,
        runner,
        recorder,
        publisher,
        track_default_revision=request.ref is None or request.ref == repository.default_ref,
    )
    if result is None:
        return await _reject(queue, claim, str(reason))
    if not await queue.mark_completed(key=claim.key, claim_id=claim.claim_id, result=result):
        raise ScanRequestClaimLostError("code-security request claim was lost before completion")
    return {"request_id": request.request_id, "status": "published", **result}


__all__ = [
    "MAX_ATTEMPTS",
    "CLAIM_RENEWAL_SECONDS",
    "REJECT_ATTEMPTS",
    "REJECT_CONFLICT",
    "REJECT_DISABLED",
    "REJECT_MALFORMED",
    "REJECT_ROLE",
    "REJECT_SCAN",
    "REJECT_SOURCE",
    "REJECT_UNREGISTERED",
    "REQUESTER_ROLES",
    "SCAN_REQUEST_OPERATION",
    "ClaimedScanRequest",
    "ReviewPublisher",
    "ReviewRecorder",
    "ScanRequest",
    "ScanOutcome",
    "ScanRequestQueue",
    "ScanRunner",
    "parse_scan_request",
    "process_scan_requests",
    "scan_result_summary",
]
