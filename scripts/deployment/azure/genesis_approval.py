#!/usr/bin/env python3
"""Load one private exact-evidence approval for a Genesis checkpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.private_output import read_private_bytes

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_EVIDENCE_FIELDS = {
    "runner-image": frozenset({"review_digest", "plan_digest"}),
    "foundation-apply": frozenset({"review_digest", "plan_digest"}),
    "runner-enrollment": frozenset({"foundation_receipt_digest"}),
    "foundation-state": frozenset({"foundation_receipt_digest", "enrollment_receipt_digest"}),
    "application-apply": frozenset({"context_digest", "plan_digest", "plan_reference_digest"}),
    "repository-config": frozenset({"plan_digest"}),
    "entra-config": frozenset({"plan_digest"}),
}


class GenesisApprovalExpiredError(ValueError):
    """Report a well-formed approval whose bounded current window has elapsed."""


@dataclass(frozen=True, slots=True)
class GenesisApproval:
    """One current human approval bound to an exact run checkpoint."""

    stage: str
    actor_digest: str
    evidence: dict[str, str]

    def authorizes(self, stage: str, **expected: str) -> bool:
        """Return false for another stage and reject changed evidence for this stage."""

        if self.stage != stage:
            return False
        if self.evidence != expected:
            raise ValueError("Genesis approval evidence does not match the current checkpoint")
        return True


def load_genesis_approval(
    path: Path | None, *, run_binding: str, source_commit: str
) -> GenesisApproval | None:
    """Read a bounded private approval and bind it to one source and run."""

    if path is None:
        return None
    if _DIGEST.fullmatch(run_binding) is None or _SOURCE_COMMIT.fullmatch(source_commit) is None:
        raise ValueError("Genesis approval context is invalid")
    value = load_json_object(
        read_private_bytes(path, max_bytes=65_536),
        label="Genesis approval",
        max_bytes=65_536,
    )
    if set(value) != {
        "schema_version",
        "run_binding",
        "source_commit",
        "stage",
        "approved",
        "approved_at",
        "expires_at",
        "actor_digest",
        "evidence",
    }:
        raise ValueError("Genesis approval fields are invalid")
    if (
        value.get("schema_version") != "fdai.genesis-approval.v1"
        or value.get("run_binding") != run_binding
        or value.get("source_commit") != source_commit
        or value.get("approved") is not True
    ):
        raise ValueError("Genesis approval does not match the current run")
    approved_at = _utc_timestamp(value.get("approved_at"))
    expires_at = _utc_timestamp(value.get("expires_at"))
    now = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
    if expires_at - approved_at > timedelta(hours=1) or approved_at > now or now >= expires_at:
        raise GenesisApprovalExpiredError(
            "Genesis approval is expired or outside its current window"
        )
    stage = value.get("stage")
    actor_digest = value.get("actor_digest")
    evidence = value.get("evidence")
    if not isinstance(stage, str) or stage not in _EVIDENCE_FIELDS:
        raise ValueError("Genesis approval stage is invalid")
    if not isinstance(actor_digest, str) or _DIGEST.fullmatch(actor_digest) is None:
        raise ValueError("Genesis approval actor digest is invalid")
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS[stage]:
        raise ValueError("Genesis approval evidence fields are invalid")
    normalized: dict[str, str] = {}
    for key, item in evidence.items():
        if not isinstance(key, str) or not isinstance(item, str) or _DIGEST.fullmatch(item) is None:
            raise ValueError("Genesis approval evidence digest is invalid")
        normalized[key] = item
    return GenesisApproval(stage=stage, actor_digest=actor_digest, evidence=normalized)


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Genesis approval timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Genesis approval timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Genesis approval timestamp is invalid")
    return parsed.astimezone(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
