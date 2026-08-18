"""One pre-dispatch safeguard contract shared by every execution path.

FDAI-CONST-007 requires all seven safeguards on any action that changes a managed
resource, external system, durable artifact, approval state, or notification state:

1. a machine-evaluable stop condition;
2. a tested rollback or bounded recovery path;
3. a computed impact scope and blast-radius limit;
4. a successful what-if or dry-run receipt;
5. a held logical-target lock with causal ordering;
6. a stable idempotency key with duplicate suppression;
7. an append-only audit intent persisted before the side effect.

Before this module the PR path proved all seven while ``direct_api`` and ``tool_call`` each
proved a subset, with their own copies of the lock-key and fingerprint helpers. A safeguard
that every path re-implements is a safeguard no single test can hold, so this module owns
the checks that run before dispatch and the values a caller must carry into its lock and
audit calls.

What stays with the caller is what only the caller can do: acquiring the lock, persisting
the audit intent, and calling its adapter. This module grants no execution authority and
never decides that an action may run. It reports which declared safeguards are missing, and
a refusal is the only answer it can give about eligibility.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fdai.shared.contracts.models import Action
from fdai.shared.contracts.models.enums import ExecutionPath

STOP_CONDITION = "stop_condition"
ROLLBACK = "rollback"
BLAST_RADIUS = "blast_radius"
DRY_RUN_RECEIPT = "dry_run_receipt"
TARGET_LOCK = "target_lock"
IDEMPOTENCY_KEY = "idempotency_key"
AUDIT_INTENT = "audit_intent"

#: Not one of the seven. An action with no citing rule has no evidence to audit, so it is
#: refused before dispatch, but attributing that refusal to a safeguard would misreport
#: which constitutional guarantee failed.
EVIDENCE_CITATION = "evidence_citation"

#: The seven safeguard ids, in constitutional order.
SEVEN_SAFEGUARDS: tuple[str, ...] = (
    STOP_CONDITION,
    ROLLBACK,
    BLAST_RADIUS,
    DRY_RUN_RECEIPT,
    TARGET_LOCK,
    IDEMPOTENCY_KEY,
    AUDIT_INTENT,
)

#: Every shipped execution path declares all seven. A path added to
#: :class:`ExecutionPath` without a row here fails the focused contract test rather than
#: silently inheriting a weaker guarantee.
REQUIRED_SAFEGUARDS: Mapping[ExecutionPath, tuple[str, ...]] = MappingProxyType(
    {path: SEVEN_SAFEGUARDS for path in ExecutionPath}
)


@dataclass(frozen=True, slots=True)
class SafeguardRefusal:
    """Why one action is ineligible for dispatch."""

    safeguard: str
    reason: str


@dataclass(frozen=True, slots=True)
class SafeguardReceipt:
    """The pre-dispatch values a path must carry into its lock and audit calls."""

    execution_path: ExecutionPath
    execution_fingerprint: str
    dry_run_receipt: str
    idempotency_key: str
    idempotency_lock_key: str
    resource_lock_key: str


def missing_safety_invariant(action: Action) -> str | None:
    """Return a message for the first missing safety invariant, or ``None``.

    The pydantic model already requires the fields; this guard is defense-in-depth against
    a caller that produced an ``Action`` via :func:`dataclasses.replace` or a partial dict.
    """

    if not action.stop_condition.strip():
        return "action.stop_condition MUST NOT be empty (safety invariant 1)"
    if not action.rollback_ref.kind:
        return "action.rollback_ref.kind MUST be set (safety invariant 2)"
    if action.blast_radius is None:
        # unreachable via pydantic, but keeps the intent legible.
        return "action.blast_radius MUST be set (safety invariant 3)"
    if not action.citing_rules:
        return "action.citing_rules MUST include at least one rule id"
    return None


def evaluate_pre_dispatch(
    action: Action,
    *,
    execution_path: ExecutionPath,
    plan_digest: str,
    plan_kind: str,
) -> SafeguardReceipt | SafeguardRefusal:
    """Check the pre-dispatch safeguards and return the values dispatch must carry.

    ``plan_digest`` is the path's what-if artifact: the rendered patch for a PR path, the
    canonical provider request for ``direct_api``, or the canonical tool request for
    ``tool_call``. An empty digest means no dry run happened, which is a refusal rather
    than a receipt carrying a blank field.
    """

    invariant_reason = missing_safety_invariant(action)
    if invariant_reason is not None:
        return SafeguardRefusal(_invariant_safeguard(invariant_reason), invariant_reason)

    if not action.idempotency_key.strip():
        return SafeguardRefusal(
            IDEMPOTENCY_KEY,
            "action.idempotency_key MUST NOT be empty (safety invariant 6)",
        )
    if not action.target_resource_ref.strip():
        return SafeguardRefusal(
            TARGET_LOCK,
            "action.target_resource_ref MUST NOT be empty (safety invariant 5)",
        )
    if not plan_digest.strip():
        return SafeguardRefusal(
            DRY_RUN_RECEIPT,
            "a dry-run artifact MUST exist before dispatch (safety invariant 4)",
        )

    fingerprint = execution_fingerprint(action=action, execution_path=execution_path)
    return SafeguardReceipt(
        execution_path=execution_path,
        execution_fingerprint=fingerprint,
        dry_run_receipt=dry_run_receipt(
            execution_fingerprint=fingerprint,
            plan_digest=plan_digest,
            plan_kind=plan_kind,
        ),
        idempotency_key=action.idempotency_key,
        idempotency_lock_key=idempotency_lock_key(action.idempotency_key),
        resource_lock_key=resource_lock_key(action.target_resource_ref),
    )


def execution_fingerprint(*, action: Action, execution_path: ExecutionPath) -> str:
    """Return the canonical digest of the safeguard-bearing fields of one action."""

    payload = {
        "action_id": str(action.action_id),
        "event_id": str(action.event_id),
        "action_type": action.action_type,
        "target_resource_ref": action.target_resource_ref,
        "operation": action.operation.value,
        "params": dict(action.params),
        "stop_condition": action.stop_condition,
        "rollback": {
            "kind": action.rollback_ref.kind.value,
            "reference": action.rollback_ref.reference,
        },
        "blast_radius": {
            "scope": action.blast_radius.scope.value,
            "count": action.blast_radius.count,
            "rate_per_minute": action.blast_radius.rate_per_minute,
        },
        "mode": action.mode.value,
        "executor_identity_ref": action.executor_identity_ref,
        "citing_rules": sorted(action.citing_rules),
        "execution_path": execution_path.value,
    }
    return _sha256(payload)


def dry_run_receipt(*, execution_fingerprint: str, plan_digest: str, plan_kind: str) -> str:
    """Return the content-addressed receipt for one dry-run artifact."""

    return "sha256:" + _sha256(
        {
            "execution_fingerprint": execution_fingerprint,
            "plan_digest": plan_digest,
            "plan_kind": plan_kind,
        }
    )


def plan_digest_for_text(text: str) -> str:
    """Return the digest of a rendered text artifact such as a patch."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_digest_for_mapping(payload: Mapping[str, object]) -> str:
    """Return the digest of a canonical JSON-compatible request payload."""

    return _sha256(payload)


def idempotency_lock_key(key: str) -> str:
    """Return the logical lock key that serializes one idempotency key."""

    return f"fdai:idempotency:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def resource_lock_key(resource_ref: str) -> str:
    """Return the logical lock key that serializes one target resource."""

    return f"fdai:resource:{resource_ref}"


def _invariant_safeguard(reason: str) -> str:
    """Map an invariant message back to the safeguard it belongs to."""

    if "stop_condition" in reason:
        return STOP_CONDITION
    if "rollback_ref" in reason:
        return ROLLBACK
    if "blast_radius" in reason:
        return BLAST_RADIUS
    return EVIDENCE_CITATION


def _sha256(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "AUDIT_INTENT",
    "BLAST_RADIUS",
    "DRY_RUN_RECEIPT",
    "EVIDENCE_CITATION",
    "IDEMPOTENCY_KEY",
    "REQUIRED_SAFEGUARDS",
    "ROLLBACK",
    "SEVEN_SAFEGUARDS",
    "STOP_CONDITION",
    "TARGET_LOCK",
    "SafeguardReceipt",
    "SafeguardRefusal",
    "dry_run_receipt",
    "evaluate_pre_dispatch",
    "execution_fingerprint",
    "idempotency_lock_key",
    "missing_safety_invariant",
    "plan_digest_for_mapping",
    "plan_digest_for_text",
    "resource_lock_key",
]
