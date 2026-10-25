"""Pull-only catalog updates: check the bound Release Hub, decide by policy, adopt, then plan.

Nothing here is reachable from the Release Hub. The Lifecycle Hub starts every poll, verifies the
signature with the key pinned at deployment, and asks the Rego policy whether a person must
review the change. Adoption never applies a Plan; the installation Agent still verifies and
executes under its own local envelope.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from fdai_lifecycle_hub.adoption_policy import (
    PolicyDecision,
    decision_record,
    evaluate_policy,
    policy_input,
    summarize_change,
)
from fdai_lifecycle_hub.catalog_import import load_pinned_export, verify_export_signature
from fdai_lifecycle_hub.configuration import ConfigurationRevisionCandidate
from fdai_lifecycle_hub.configuration_keys import KeyBindingError
from fdai_lifecycle_hub.domain import utc_now
from fdai_lifecycle_hub.remote_catalog import FetchedExport, RemoteCatalog
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

logger = logging.getLogger(__name__)
POLICY_ACTOR = "policy:catalog-adoption"
MIN_JITTER_START_SECONDS = 5.0
MAX_JITTER_START_SECONDS = 30.0


class CandidateChangedError(ValueError):
    """The source moved after the operator reviewed a candidate."""


@dataclass(frozen=True, slots=True)
class CheckRecord:
    checked_at: str
    outcome: str
    detail: str
    candidate: dict[str, Any] | None = None
    plans: tuple[dict[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "outcome": self.outcome,
            "detail": self.detail,
            "candidate": self.candidate,
            "plans": list(self.plans),
        }


class CatalogUpdater:
    def __init__(
        self,
        catalog: RemoteCatalog,
        store: HubStore,
        key: HubSigningKey,
        *,
        clock: Callable[[], datetime] = utc_now,
        configuration_candidates: Mapping[str, tuple[ConfigurationRevisionCandidate, int]]
        | None = None,
        evaluate: Callable[[dict[str, Any]], PolicyDecision] = evaluate_policy,
    ) -> None:
        self.catalog, self.store, self.key = catalog, store, key
        self.clock, self.evaluate = clock, evaluate
        self.configuration_candidates = configuration_candidates or {}
        self._lock = threading.Lock()
        self._last: CheckRecord | None = None

    @property
    def interval_seconds(self) -> int:
        return self.catalog.source.check_interval_seconds

    def check(self) -> CheckRecord:
        """Poll once. Adopt when policy allows, otherwise leave a candidate for review."""

        with self._lock:
            return self._remember(self._check())

    def apply(self, *, revision: int, sha256: str, actor: str) -> CheckRecord:
        """Adopt the candidate an operator reviewed, if the source still offers exactly it."""

        with self._lock:
            now = self.clock()
            fetched = self._poll(None)
            if fetched is None:
                raise CandidateChangedError("Catalog source did not return a candidate.")
            candidate, decision, view = self._assess(fetched, now)
            if view["revision"] != revision or view["sha256"] != sha256:
                self._remember(self._record(now, "review_required", decision, view))
                raise CandidateChangedError("The candidate changed; review the new one.")
            if not view["signature_verified"]:
                raise ValueError("Only a signature-verified candidate can be reviewed here.")
            reason = "operator_review:" + ",".join(decision.reasons or ("policy_allow",))
            self.catalog.adopt(fetched, actor=actor, reason=reason[:500], now=now)
            record = CheckRecord(
                now.isoformat(),
                "adopted",
                "operator_review",
                view,
                self._recompute_all(now),
            )
            return self._remember(record)

    def status(self) -> dict[str, Any]:
        source = self.catalog.source
        adoption = source.adoption
        now = self.clock()
        previous, expires_at = self.catalog.accepted_baseline()
        state = self.catalog.status()
        return {
            "mode": adoption.mode,
            "allowed_channels": list(adoption.allowed_channels),
            "max_new_releases": adoption.max_new_releases,
            "check_interval_seconds": self.interval_seconds,
            "access": source.access,
            "authorization": {
                "authorized_by": adoption.authorized_by,
                "expires_at": adoption.authorization_expires_at,
                "valid": adoption.authorization_valid(now),
            }
            if adoption.authorized_by is not None
            else None,
            "accepted": {
                "revision": state["minimum_revision"],
                "sha256": state["accepted_sha256"],
                "expires_at": expires_at,
                "release_count": len(previous.releases) if previous else 0,
            }
            if state["imported"]
            else None,
            "last_check": self._last.to_json() if self._last else None,
            "events": self.catalog.recent_events(),
        }

    def _remember(self, record: CheckRecord) -> CheckRecord:
        self._last = record
        logger.info("hub_catalog_check outcome=%s detail=%s", record.outcome, record.detail)
        return record

    def _poll(self, accepted_digest: str | None) -> FetchedExport | None:
        return self.catalog.fetch_signed(self.catalog.source, accepted_digest=accepted_digest)

    def _record(
        self, now: datetime, outcome: str, decision: PolicyDecision, view: dict[str, Any]
    ) -> CheckRecord:
        return CheckRecord(
            now.isoformat(),
            outcome,
            ",".join(decision.reasons) if decision.reasons else "policy_allow",
            view,
        )

    def _assess(
        self, fetched: FetchedExport, now: datetime
    ) -> tuple[Any, PolicyDecision, dict[str, Any]]:
        """Verify the exact bytes and decide. Raises ValueError for an unusable candidate."""

        state = self.catalog.status()
        public_key = self.catalog.source.public_key()
        verified = verify_export_signature(fetched.raw, fetched.signature, public_key)
        digest = _digest(fetched.raw)
        candidate = load_pinned_export(
            fetched.raw,
            expected_sha256=digest,
            public_key=public_key,
            now=now,
            minimum_revision=state["minimum_revision"],
            previous_sha256=state["accepted_sha256"],
        )
        previous, _expires = self.catalog.accepted_baseline()
        change = summarize_change(previous, candidate)
        decision = self.evaluate(
            policy_input(
                config=self.catalog.source.adoption,
                change=change,
                baseline_present=previous is not None,
                signature_verified=verified,
                now=now,
            )
        )
        document = json.loads(fetched.raw)
        view = {
            "revision": document["revision"],
            "sha256": digest,
            "expires_at": document["expires_at"],
            "signature_verified": verified,
            "key_id": fetched.key_id,
            "decision": decision_record(decision),
            "change": change,
            "accepted_revision": state["minimum_revision"] if state["imported"] else None,
        }
        return candidate, decision, view

    def _check(self) -> CheckRecord:
        now = self.clock()
        try:
            state = self.catalog.status()
            fetched = self._poll(state["accepted_sha256"])
        except (ValueError, SQLAlchemyError):
            return CheckRecord(now.isoformat(), "failed", "source_unavailable")
        if fetched is None:
            return CheckRecord(now.isoformat(), "unchanged", "source_reports_current")
        if _digest(fetched.raw) == state["accepted_sha256"]:
            return CheckRecord(now.isoformat(), "unchanged", "digest_already_accepted")
        if not fetched.signature:
            return CheckRecord(now.isoformat(), "failed", "signature_missing")
        try:
            _candidate, decision, view = self._assess(fetched, now)
        except (ValueError, KeyError, SQLAlchemyError):
            return CheckRecord(now.isoformat(), "failed", "candidate_invalid")
        if not view["signature_verified"]:
            return CheckRecord(now.isoformat(), "failed", "signature_invalid", view)
        if not decision.allow:
            self.catalog.record_review_needed(
                revision=view["revision"],
                digest=view["sha256"],
                reason=",".join(decision.reasons)[:500],
                now=now,
            )
            return self._record(now, "review_required", decision, view)
        try:
            self.catalog.adopt(fetched, actor=POLICY_ACTOR, reason="policy_allow", now=now)
        except (ValueError, SQLAlchemyError):
            return CheckRecord(now.isoformat(), "failed", "adoption_rejected", view)
        return CheckRecord(
            now.isoformat(), "adopted", "policy_allow", view, self._recompute_all(now)
        )

    def _recompute_all(self, now: datetime) -> tuple[dict[str, Any], ...]:
        """Issue Plans for every enrolled installation. A Plan is never applied here."""

        results = []
        for overview in self.store.list_installations():
            installation_id = overview.installation.installation_id
            selected = self.configuration_candidates.get(installation_id)
            try:
                outcome = self.catalog.recompute(
                    self.store,
                    installation_id,
                    self.key,
                    now=now,
                    configuration_revision=selected[0] if selected else None,
                    configuration_key_version=selected[1] if selected else None,
                )
                results.append({"installation_id": installation_id, "outcome": outcome.kind})
            except (ValueError, KeyBindingError, SQLAlchemyError) as error:
                logger.warning(
                    "hub_plan_recompute_failed installation=%s category=%s",
                    installation_id,
                    type(error).__name__,
                )
                results.append(
                    {
                        "installation_id": installation_id,
                        "outcome": "error",
                        "reason": type(error).__name__,
                    }
                )
        return tuple(results)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


async def run_periodic(
    updater: CatalogUpdater,
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
    rng: random.Random | None = None,
    jitter: float = 0.1,
) -> None:
    """Poll on the configured interval, with startup jitter and capped retry after a failure."""

    interval = updater.interval_seconds
    if interval == 0:
        return
    generator = rng or random.Random()  # noqa: S311 - scheduling jitter, not a secret
    await sleep(generator.uniform(MIN_JITTER_START_SECONDS, MAX_JITTER_START_SECONDS))
    failures = 0
    while True:
        try:
            record = await run_in_threadpool(updater.check)
            failures = failures + 1 if record.outcome == "failed" else 0
        except Exception as error:  # noqa: BLE001 - one bad cycle must not stop future checks
            logger.error("hub_catalog_check_crashed category=%s", type(error).__name__)
            failures += 1
        delay = interval if failures == 0 else min(interval, 60 * 2 ** min(failures - 1, 6))
        await sleep(delay * (1 + generator.uniform(-jitter, jitter)))
