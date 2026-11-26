"""Current-admission gate for deployment-owned operating-intent authority.

Admitting the six-type operating-intent source once, at startup, is not enough. A
source that was complete, pinned, and fresh when the process started can later fall
out of its effective interval, exceed its declared freshness, or disappear from the
deployment mount entirely. The projected graph objects survive that transition - they
are evidence and history - so an authority consumer that reads them directly would
keep granting maintenance authority from a source nothing currently vouches for.

This module is the read side of the bounded revalidation contract. The runtime
revalidation worker durably records what it most recently proved about the source;
every authority consumer resolves that record - status, pinned revision and digest,
rollout generation, owned object identities, and the age of the proof - instead of
trusting a raw graph object.

Three fences make that record safe to read across a rolling deployment.

*Binding* - a reader carries the exact revision and whole-document digest its own
configuration pins, so a record written under any other binding is rejected rather
than accepted just because it parses.

*Generation* - the record carries the rollout generation that wrote it. A reader
rejects a record from any other generation, so an old replica's revalidation pass
cannot authorize a newer rollout, and a newer rollout's record cannot silently
authorize an old replica reading a graph it never validated.

*Ownership* - the record names the intent-source object identities the admission
actually vouches for. A global ``admitted`` verdict therefore cannot bless a
``ChangeWindow`` injected by the generic ``FDAI_OPERATING_MODEL_PATH`` snapshot or by
the continuous operating-model worker, neither of which this pin protects.

Absence is fail-closed for a configured reader: a deleted, corrupted, or
not-yet-written record proves nothing, so it denies. Generic
``FDAI_OPERATING_MODEL_PATH`` compatibility survives only through explicit
configuration - a reader with no expectation is declaring that no deployment-owned
intent binding governs this graph, and it neither grants nor withholds anything of
its own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.shared.providers.state_store import StateStore

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

OPERATING_INTENT_SOURCE_ADMISSION_KEY = "operating-intent-source:admission"
"""Durable state key holding the most recent operating-intent source admission."""

MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS = 86_400
"""Upper bound on any writer-declared admission validity window (one day)."""

MAX_ADMITTED_OBJECT_IDS = 4_096
"""Upper bound on the owned identities one admission record may enumerate.

Bounded because the record is read on every maintenance-authority decision. A source
large enough to exceed this cannot be admitted at all, rather than being admitted
with a truncated - and therefore over-permissive - ownership set.
"""


class OperatingIntentAdmissionStatus(StrEnum):
    """Resolved authority disposition of the deployment-owned intent source."""

    UNBOUND = "unbound"
    ADMITTED = "admitted"
    EXPIRED = "expired"
    QUARANTINED = "quarantined"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    BINDING_MISMATCH = "binding_mismatch"


_DENYING_RECORD_STATUSES = frozenset({"quarantined", "unavailable"})


@dataclass(frozen=True, slots=True)
class OperatingIntentAdmissionExpectation:
    """What one consumer's own configuration pins the admission record to.

    Built from the same process configuration that drives the writer, so a reader and
    the writer in one replica always agree. ``generation`` is the operator-supplied
    rollout counter (``FDAI_OPERATING_INTENT_SOURCE_GENERATION``): it is the only
    value that orders two otherwise equally valid bindings, which is exactly what a
    rolling deployment needs so an old replica cannot overwrite or authorize a newer
    rollout's admission.
    """

    expected_revision: str
    expected_sha256: str
    generation: int

    def __post_init__(self) -> None:
        if not self.expected_revision.strip():
            raise ValueError(
                "OperatingIntentAdmissionExpectation.expected_revision MUST be non-empty"
            )
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise ValueError("OperatingIntentAdmissionExpectation.expected_sha256 MUST be SHA-256")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise ValueError("OperatingIntentAdmissionExpectation.generation MUST be an integer")
        if self.generation < 1:
            raise ValueError("OperatingIntentAdmissionExpectation.generation MUST be >= 1")


@dataclass(frozen=True, slots=True)
class OperatingIntentAdmission:
    """One resolved judgement about whether intent authority is currently backed.

    ``grants_intent_authority`` is deliberately not the same as "the source is
    healthy": an unconfigured binding grants nothing of its own and simply does not
    withhold the pre-existing generic operating-model behavior. Only ``ADMITTED``
    reflects a source that a bounded revalidation recently proved complete, pinned,
    and fresh under this consumer's own binding and rollout generation.

    ``owned_object_ids`` is the ownership fence. ``None`` means no deployment-owned
    intent binding governs this graph, so a consumer applies no ownership filter and
    keeps its pre-existing behavior. A frozen set - possibly empty - means the
    admission vouches for exactly those identities and for nothing else.
    """

    status: OperatingIntentAdmissionStatus
    grants_intent_authority: bool
    reason: str | None = None
    source_revision: str | None = None
    snapshot_digest: str | None = None
    generation: int | None = None
    owned_object_ids: frozenset[str] | None = None
    validated_at: datetime | None = None


def evaluate_operating_intent_admission(
    raw: Mapping[str, object] | None,
    *,
    now: datetime,
    expectation: OperatingIntentAdmissionExpectation | None,
) -> OperatingIntentAdmission:
    """Resolve one durable admission record into a current authority judgement.

    ``now`` MUST be supplied by the caller - normally the exact decision instant an
    authority consumer is judging - so the age check stays deterministic and so
    authority is evaluated at the time it is claimed rather than at read time.

    ``expectation`` is this consumer's own configured binding. ``None`` means the
    consumer is explicitly unconfigured: no deployment-owned intent source governs
    this graph, so the record is not consulted at all and the pre-existing generic
    behavior is preserved without an ownership fence. Any other value makes the
    judgement strict - absence, a foreign binding, a foreign generation, a missing
    ownership set, or an expired proof all deny.
    """

    if now.tzinfo is None:
        raise ValueError("operating intent admission 'now' MUST be timezone-aware")
    if expectation is None:
        return OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.UNBOUND,
            grants_intent_authority=True,
            reason="no deployment-owned operating-intent source binding is configured",
        )
    if raw is None:
        return OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.UNAVAILABLE,
            grants_intent_authority=False,
            reason=(
                "a deployment-owned operating-intent source is configured but no current "
                "admission record exists"
            ),
        )
    status = raw.get("status")
    reason = raw.get("reason")
    reason_text = reason if isinstance(reason, str) and reason else None
    if status == "unconfigured":
        return _binding_mismatch(
            "the durable admission reports an unconfigured binding while this consumer is "
            "configured"
        )
    if status in _DENYING_RECORD_STATUSES:
        return OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus(status),
            grants_intent_authority=False,
            reason=reason_text,
            validated_at=_optional_timestamp(raw.get("validated_at")),
        )
    if status != "admitted":
        return _malformed("operating intent admission status is missing or unrecognized")
    source_revision = raw.get("source_revision")
    snapshot_digest = raw.get("snapshot_digest")
    if not isinstance(source_revision, str) or not source_revision.strip():
        return _malformed("admitted operating intent admission is missing source_revision")
    if not isinstance(snapshot_digest, str) or _SHA256.fullmatch(snapshot_digest) is None:
        return _malformed("admitted operating intent admission is missing a SHA-256 digest")
    generation = raw.get("binding_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        return _malformed("admitted operating intent admission is missing binding_generation")
    if source_revision != expectation.expected_revision:
        return _binding_mismatch(
            "the durable admission pins a different source revision than this consumer's binding"
        )
    if snapshot_digest != expectation.expected_sha256:
        return _binding_mismatch(
            "the durable admission pins a different whole-document digest than this consumer's "
            "binding"
        )
    if generation != expectation.generation:
        return _binding_mismatch(
            "the durable admission was written by a different rollout generation than this "
            "consumer's"
        )
    owned_object_ids = _owned_object_ids(raw.get("owned_object_ids"))
    if owned_object_ids is None:
        return _malformed("admitted operating intent admission has an unusable owned_object_ids")
    validated_at = _optional_timestamp(raw.get("validated_at"))
    if validated_at is None:
        return _malformed("admitted operating intent admission is missing validated_at")
    max_age_seconds = raw.get("max_age_seconds")
    if (
        isinstance(max_age_seconds, bool)
        or not isinstance(max_age_seconds, int)
        or max_age_seconds < 1
        or max_age_seconds > MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS
    ):
        return _malformed("admitted operating intent admission has an unusable max_age_seconds")
    age_seconds = (now - validated_at).total_seconds()
    if age_seconds < 0:
        return _malformed("admitted operating intent admission has a future validated_at")
    if age_seconds > max_age_seconds:
        return OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.EXPIRED,
            grants_intent_authority=False,
            reason=(
                "the deployment-owned operating-intent source has not been revalidated "
                "within its declared validity window"
            ),
            source_revision=source_revision,
            snapshot_digest=snapshot_digest,
            generation=generation,
            validated_at=validated_at,
        )
    return OperatingIntentAdmission(
        status=OperatingIntentAdmissionStatus.ADMITTED,
        grants_intent_authority=True,
        source_revision=source_revision,
        snapshot_digest=snapshot_digest,
        generation=generation,
        owned_object_ids=owned_object_ids,
        validated_at=validated_at,
    )


class StateStoreOperatingIntentAdmissionReader:
    """Read the durable operating-intent admission an authority consumer must gate on.

    Read-only by construction: it never projects, repairs, or re-admits a source. A
    state-store read failure is not swallowed into a permissive answer - it
    propagates to the caller, whose own fail-closed path denies.

    ``expectation`` binds the reader to the exact revision, whole-document digest, and
    rollout generation this process is configured to trust. Passing ``None`` is an
    explicit declaration that no deployment-owned intent source is configured, and is
    the only way to keep the pre-existing generic behavior.
    """

    def __init__(
        self,
        store: StateStore,
        *,
        expectation: OperatingIntentAdmissionExpectation | None,
    ) -> None:
        self._store = store
        self._expectation = expectation

    async def resolve(self, *, now: datetime) -> OperatingIntentAdmission:
        if self._expectation is None:
            return evaluate_operating_intent_admission(None, now=now, expectation=None)
        raw = await self._store.read_state(OPERATING_INTENT_SOURCE_ADMISSION_KEY)
        return evaluate_operating_intent_admission(raw, now=now, expectation=self._expectation)


def _malformed(reason: str) -> OperatingIntentAdmission:
    return OperatingIntentAdmission(
        status=OperatingIntentAdmissionStatus.MALFORMED,
        grants_intent_authority=False,
        reason=reason,
    )


def _binding_mismatch(reason: str) -> OperatingIntentAdmission:
    return OperatingIntentAdmission(
        status=OperatingIntentAdmissionStatus.BINDING_MISMATCH,
        grants_intent_authority=False,
        reason=reason,
    )


def _owned_object_ids(value: object) -> frozenset[str] | None:
    """Return the vouched-for identities, or ``None`` when they are unusable.

    An admitted record MUST enumerate its ownership explicitly. An empty list is a
    meaningful answer - the source vouches for nothing right now - while a missing,
    oversized, or malformed list is not, and denies.
    """

    if not isinstance(value, list) or len(value) > MAX_ADMITTED_OBJECT_IDS:
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return None
    return frozenset(str(item) for item in value)


def _optional_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = [
    "MAX_ADMITTED_OBJECT_IDS",
    "MAX_OPERATING_INTENT_ADMISSION_AGE_SECONDS",
    "OPERATING_INTENT_SOURCE_ADMISSION_KEY",
    "OperatingIntentAdmission",
    "OperatingIntentAdmissionExpectation",
    "OperatingIntentAdmissionStatus",
    "StateStoreOperatingIntentAdmissionReader",
    "evaluate_operating_intent_admission",
]
