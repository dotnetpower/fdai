"""Assess one catalog candidate under signed roles: authenticate, bind, summarize and decide."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from fdai_lifecycle_hub.adoption_policy import (
    PolicyDecision,
    decision_record,
    policy_input,
    summarize_change,
)
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.catalog_integrity import (
    IntegrityAssessment,
    IntegrityFloors,
    bind_export,
    export_keys,
    export_signature_verified,
)
from fdai_lifecycle_hub.remote_catalog import FetchedExport, RemoteCatalog


class IntegrityCheckError(ValueError):
    """The export does not match the verified roles. `detail` is a stable status code."""

    def __init__(self, detail: str, assessment: IntegrityAssessment) -> None:
        super().__init__(detail)
        self.detail = detail
        self.assessment = assessment


@dataclass(frozen=True, slots=True)
class TufCandidate:
    decision: PolicyDecision
    view: dict[str, Any]
    baseline: str | None
    assessment: IntegrityAssessment


def assess_tuf_candidate(
    catalog: RemoteCatalog,
    evaluate: Callable[[dict[str, Any]], PolicyDecision],
    fetched: FetchedExport,
    assessment: IntegrityAssessment,
    floors: IntegrityFloors,
    now: datetime,
) -> TufCandidate:
    """Raise IntegrityCheckError when the bytes do not match the roles, ValueError when unusable."""

    root = assessment.root
    if not assessment.verified or root is None:
        raise IntegrityCheckError("integrity_not_verified", assessment)
    if not export_signature_verified(fetched.raw, fetched.signature, root):
        raise IntegrityCheckError("signature_invalid", assessment)
    reason = bind_export(assessment, raw=fetched.raw, floors=floors)
    if reason is not None:
        raise IntegrityCheckError(
            "integrity_not_verified", replace(assessment, verified=False, reason_code=reason)
        )
    state = catalog.status()
    digest = hashlib.sha256(fetched.raw).hexdigest()
    candidate = load_pinned_export(
        fetched.raw,
        expected_sha256=digest,
        public_key=export_keys(root),
        now=now,
        minimum_revision=state["minimum_revision"],
        previous_sha256=state["accepted_sha256"],
        enforce_expiry=False,
    )
    previous, _expires, baseline = catalog.accepted_baseline()
    change = summarize_change(previous, candidate)
    decision = evaluate(
        policy_input(
            config=catalog.source.adoption,
            change=change,
            baseline_present=previous is not None,
            signature_verified=True,
            now=now,
            integrity=assessment.policy_facts(),
        )
    )
    document = json.loads(fetched.raw)
    view = {
        "revision": document["revision"],
        "sha256": digest,
        "expires_at": document["expires_at"],
        "signature_verified": True,
        "key_id": fetched.key_id,
        "decision": decision_record(decision),
        "change": change,
        "accepted_revision": state["minimum_revision"] if state["imported"] else None,
        "integrity": assessment.to_json(),
    }
    return TufCandidate(decision, view, baseline, assessment)
