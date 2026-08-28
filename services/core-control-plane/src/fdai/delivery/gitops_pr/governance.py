"""Governed PR delivery for catalog governance documents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from fdai.delivery.gitops_pr.governance_writers import GovernanceDocument
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import RemediationPr, RemediationPrPublisher
from fdai.shared.providers.state_store import StateStore

_RETIREMENT_PREFIX = "rule-catalog/retirements/"
_EXEMPTION_PREFIX = "rule-catalog/exemptions/"
_SUPPORTED = {
    "rule-retirement": ("governance.retire-rule", _RETIREMENT_PREFIX, ".yaml"),
    "exemption": ("governance.grant-exemption", _EXEMPTION_PREFIX, ".json"),
}
_MAX_DOCUMENT_BYTES = 256 * 1024
# Bumped because the receipt now binds a stable source-event identity rather
# than treating a correlation group as one event.
_SCHEMA_VERSION = "1.2.0"


class GovernancePrError(RuntimeError):
    """Raised when a governance document cannot enter the reviewed PR flow."""


@dataclass(frozen=True, slots=True)
class GovernancePrLifecycleReceipt:
    """Replayable evidence that a governance PR is open and not merged."""

    action_type_name: str
    idempotency_key: str
    correlation_id: str
    source_event_id: str
    document_digest: str
    document_path: str
    pr_ref: str
    url: str | None
    state: str = "open"
    merge_required: bool = True
    applied: bool = False
    already_existed: bool = False
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if self.state not in {"open", "merged", "closed"}:
            raise ValueError("governance PR receipt state is invalid")
        if self.state == "open" and (not self.merge_required or self.applied):
            raise ValueError("open governance PR receipt MUST require a human merge")
        if self.state == "merged" and (self.merge_required or not self.applied):
            raise ValueError("merged governance PR receipt MUST be applied")
        if self.state == "closed" and (self.merge_required or self.applied):
            raise ValueError("closed governance PR receipt MUST remain unapplied")
        if (
            not self.pr_ref
            or not self.idempotency_key
            or not self.correlation_id.strip()
            or not self.source_event_id.strip()
            or len(self.document_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.document_digest)
            or not self.recorded_at
        ):
            raise ValueError("governance PR receipt identity is invalid")

    def as_json(self) -> dict[str, object]:
        """Return stable machine evidence suitable for replay."""
        return {
            "schema_version": _SCHEMA_VERSION,
            "action_type_name": self.action_type_name,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "source_event_id": self.source_event_id,
            "document_digest": self.document_digest,
            "document_path": self.document_path,
            "pr_ref": self.pr_ref,
            "url": self.url,
            "state": self.state,
            "merge_required": self.merge_required,
            "applied": self.applied,
            "already_existed": self.already_existed,
            "recorded_at": self.recorded_at,
        }


class GovernancePrLifecycleStore(Protocol):
    """Durable store for open-to-merge governance lifecycle evidence."""

    async def save(self, receipt: GovernancePrLifecycleReceipt) -> None: ...

    async def load(self, idempotency_key: str) -> GovernancePrLifecycleReceipt | None: ...


class StateStoreGovernancePrLifecycleStore:
    """Persist lifecycle receipts with append-only audit evidence."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def save(self, receipt: GovernancePrLifecycleReceipt) -> None:
        key = f"governance-pr-lifecycle:{receipt.idempotency_key}:{receipt.state}"
        value = receipt.as_json()
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": "fdai.delivery.gitops_pr.governance",
                "action_kind": "governance_pr.open_to_merge",
                "mode": Mode.SHADOW.value,
                "idempotency_key": receipt.idempotency_key,
                "correlation_id": receipt.correlation_id,
                "action_type_name": receipt.action_type_name,
                "document_digest": receipt.document_digest,
                "pr_ref": receipt.pr_ref,
                "state": receipt.state,
                "merge_required": receipt.merge_required,
                "applied": receipt.applied,
                "recorded_at": receipt.recorded_at,
            },
        )
        if created:
            return
        existing = await self.load(receipt.idempotency_key)
        if existing != receipt:
            raise GovernancePrError("governance PR lifecycle key collision")

    async def load(self, idempotency_key: str) -> GovernancePrLifecycleReceipt | None:
        for state in ("merged", "closed", "open"):
            raw = await self._store.read_state(f"governance-pr-lifecycle:{idempotency_key}:{state}")
            if raw is not None:
                if raw.get("schema_version") != _SCHEMA_VERSION:
                    raise GovernancePrError("unsupported governance PR lifecycle state")
                return _decode_receipt(raw)
        return None


class GovernedGovernancePrPublisher:
    """Bind pure governance writers to a write-once reviewed PR adapter.

    This publisher only opens a draft review artifact and stores an
    open-to-merge receipt. It never merges a PR or changes the active catalog.
    """

    def __init__(
        self,
        *,
        publisher: RemediationPrPublisher,
        lifecycle_store: GovernancePrLifecycleStore,
        clock: Any = None,
    ) -> None:
        self._publisher = publisher
        self._lifecycle_store = lifecycle_store
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def publish(
        self,
        document: GovernanceDocument,
        *,
        correlation_id: str,
        source_event_id: str,
    ) -> GovernancePrLifecycleReceipt:
        kind = (
            "rule-retirement"
            if document.path.startswith(_RETIREMENT_PREFIX)
            else "exemption"
            if document.path.startswith(_EXEMPTION_PREFIX)
            else ""
        )
        if not kind:
            raise GovernancePrError("governance document path is outside its canonical directory")
        supported = _SUPPORTED.get(kind)
        if supported is None or document.execution_path != "pr_native" or document.applied:
            raise GovernancePrError("governance document is not an unapplied supported PR artifact")
        if not correlation_id.strip():
            raise GovernancePrError("correlation_id MUST be non-empty")
        if not source_event_id.strip():
            raise GovernancePrError("source_event_id MUST be non-empty")
        action_type, prefix, extension = supported
        # Freeze the document once, before any read. `document.document` is a
        # plain caller-owned mapping; reading it again at render time without
        # this snapshot would let a caller mutate it between the digest below
        # and `_document_text` so the merged patch would silently diverge
        # from what was hashed, reviewed, and recorded as evidence.
        frozen_document = _snapshot(document.document)
        _validate_document_path(
            path=document.path,
            frozen_document=frozen_document,
            prefix=prefix,
            extension=extension,
        )
        _require_distinct_approval(frozen_document)
        payload = _canonical_document(frozen_document)
        digest = hashlib.sha256(payload).hexdigest()
        # The stable source event owns idempotency. The digest remains evidence
        # and drift for the same event fails closed instead of opening another PR.
        key = f"{action_type}:{source_event_id}"
        for legacy_key in (
            f"{action_type}:{digest}",
            f"{action_type}:{correlation_id}:{digest}",
        ):
            if await self._lifecycle_store.load(legacy_key) is not None:
                raise GovernancePrError(
                    "legacy governance PR lifecycle receipt requires reconciliation"
                )
        prior = await self._lifecycle_store.load(key)
        if prior is not None:
            if (
                prior.document_digest != digest
                or prior.document_path != document.path
                or prior.correlation_id != correlation_id
                or prior.source_event_id != source_event_id
            ):
                raise GovernancePrError("governance source event content drift")
            reconcile = getattr(self._publisher, "reconcile", None)
            if callable(reconcile) and prior.state == "open":
                state = await reconcile(prior.pr_ref)
                if state not in {"open", "merged", "closed"}:
                    raise GovernancePrError(
                        "governance PR adapter returned an invalid lifecycle state"
                    )
                if state != prior.state:
                    prior = GovernancePrLifecycleReceipt(
                        action_type_name=prior.action_type_name,
                        idempotency_key=prior.idempotency_key,
                        correlation_id=prior.correlation_id,
                        source_event_id=prior.source_event_id,
                        document_digest=prior.document_digest,
                        document_path=prior.document_path,
                        pr_ref=prior.pr_ref,
                        url=prior.url,
                        state=state,
                        merge_required=state == "open",
                        applied=state == "merged",
                        already_existed=True,
                        recorded_at=_rfc3339(self._clock()),
                    )
                    await self._lifecycle_store.save(prior)
            return prior
        patch = _document_text(frozen_document, action_type)
        if len(patch.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
            raise GovernancePrError("governance document exceeds its byte limit")
        receipt = await self._publisher.publish(
            RemediationPr(
                action_id=UUID(bytes=hashlib.sha256(key.encode()).digest()[:16], version=4),
                idempotency_key=key,
                rule_ids=(action_type,),
                title=f"Review {action_type}",
                body=(
                    f"Governed {action_type} change.\n"
                    "This draft is open for review and has no effect until a distinct "
                    "authorized human merges it."
                ),
                patch=patch,
                patch_path=document.path,
                labels=("shadow", f"action:{action_type}"),
                mode=Mode.SHADOW,
                metadata={"correlation_id": correlation_id, "document_digest": digest},
            )
        )
        if receipt.already_existed:
            raise GovernancePrError("existing governance PR lacks matching lifecycle evidence")
        state = receipt.state
        if state not in {"open", "merged", "closed"}:
            raise GovernancePrError("governance PR publisher returned an invalid lifecycle state")
        lifecycle = GovernancePrLifecycleReceipt(
            action_type_name=action_type,
            idempotency_key=key,
            correlation_id=correlation_id,
            source_event_id=source_event_id,
            document_digest=digest,
            document_path=document.path,
            pr_ref=receipt.pr_ref,
            url=receipt.url,
            state=state,
            merge_required=state == "open",
            applied=state == "merged",
            already_existed=receipt.already_existed,
            recorded_at=_rfc3339(self._clock()),
        )
        await self._lifecycle_store.save(lifecycle)
        return lifecycle


def _snapshot(value: Any) -> Any:
    """Return a deep, independent copy of a caller-owned JSON-shaped value.

    Called once per publish before the document is digested. Every later
    read in this module (path/identifier validation, canonicalization, and
    patch rendering) reads this same snapshot, so a caller that still holds
    and mutates the original mapping after this call cannot make the
    rendered PR patch diverge from what was hashed and recorded as evidence.
    A plain deep copy (not a frozen/proxy view) keeps the result natively
    serializable by both ``json`` and ``yaml``.
    """
    if isinstance(value, Mapping):
        return {key: _snapshot(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_snapshot(item) for item in value]
    return value


def _canonical_document(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _yaml_document(document: Mapping[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True)


def _decode_receipt(raw: Mapping[str, Any]) -> GovernancePrLifecycleReceipt:
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise GovernancePrError("unsupported governance PR lifecycle state")
    action_type_name = _required_text(raw, "action_type_name")
    idempotency_key = _required_text(raw, "idempotency_key")
    correlation_id = _required_text(raw, "correlation_id")
    source_event_id = _required_text(raw, "source_event_id")
    document_digest = _required_text(raw, "document_digest")
    if len(document_digest) != 64 or any(
        char not in "0123456789abcdef" for char in document_digest
    ):
        raise GovernancePrError("governance PR lifecycle digest is malformed")
    document_path = _required_text(raw, "document_path")
    pr_ref = _required_text(raw, "pr_ref")
    url = raw.get("url")
    if url is not None and not isinstance(url, str):
        raise GovernancePrError("governance PR lifecycle URL is malformed")
    state = raw.get("state")
    merge_required = raw.get("merge_required")
    applied = raw.get("applied")
    if state not in {"open", "merged", "closed"} or not isinstance(merge_required, bool):
        raise GovernancePrError("governance PR lifecycle state is malformed")
    if not isinstance(applied, bool) or raw.get("already_existed") not in (True, False):
        raise GovernancePrError("governance PR lifecycle flags are malformed")
    recorded_at = _required_text(raw, "recorded_at")
    return GovernancePrLifecycleReceipt(
        action_type_name=action_type_name,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_event_id=source_event_id,
        document_digest=document_digest,
        document_path=document_path,
        pr_ref=pr_ref,
        url=url,
        state=state,
        merge_required=merge_required,
        applied=applied,
        already_existed=raw["already_existed"],
        recorded_at=recorded_at,
    )


def _required_text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise GovernancePrError(f"governance PR lifecycle {name} is malformed")
    return value


def _require_distinct_approval(document: Mapping[str, Any]) -> None:
    requested = document.get("requested_by")
    approved = document.get("approved_by")
    if (
        not isinstance(requested, str)
        or not isinstance(approved, str)
        or not requested
        or not approved
        or requested == approved
    ):
        raise GovernancePrError("governance document requires a distinct approved_by principal")


def _validate_document_path(
    *,
    path: str,
    frozen_document: Mapping[str, Any],
    prefix: str,
    extension: str,
) -> None:
    if not path.startswith(prefix) or not path.endswith(extension):
        raise GovernancePrError("governance document path is outside its canonical directory")
    filename = path[len(prefix) : -len(extension)]
    if not filename or "/" in filename or "\\" in filename:
        raise GovernancePrError("governance document path filename is invalid")
    identifier_key = "rule_id" if prefix == _RETIREMENT_PREFIX else "id"
    identifier = frozen_document.get(identifier_key)
    if not isinstance(identifier, str) or identifier != filename:
        raise GovernancePrError("governance document path does not match its identifier")


def _document_text(document: Mapping[str, Any], action_type: str) -> str:
    if action_type == "governance.grant-exemption":
        return json.dumps(dict(document), indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    return _yaml_document(document)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GovernancePrError("governance lifecycle clock MUST be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "GovernancePrError",
    "GovernancePrLifecycleReceipt",
    "GovernancePrLifecycleStore",
    "GovernedGovernancePrPublisher",
    "StateStoreGovernancePrLifecycleStore",
]
