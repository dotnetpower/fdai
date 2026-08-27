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

_SUPPORTED = {
    "rule-retirement": "governance.retire-rule",
    "exemption": "governance.grant-exemption",
}
_MAX_DOCUMENT_BYTES = 256 * 1024


class GovernancePrError(RuntimeError):
    """Raised when a governance document cannot enter the reviewed PR flow."""


@dataclass(frozen=True, slots=True)
class GovernancePrLifecycleReceipt:
    """Replayable evidence that a governance PR is open and not merged."""

    action_type_name: str
    idempotency_key: str
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
        if self.state != "open" or not self.merge_required or self.applied:
            raise ValueError("governance PR receipt MUST remain open until a human merge")
        if (
            not self.pr_ref
            or not self.idempotency_key
            or len(self.document_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.document_digest)
            or not self.recorded_at
        ):
            raise ValueError("governance PR receipt identity is invalid")

    def as_json(self) -> dict[str, object]:
        """Return stable machine evidence suitable for replay."""
        return {
            "schema_version": "1.0.0",
            "action_type_name": self.action_type_name,
            "idempotency_key": self.idempotency_key,
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
        key = f"governance-pr-lifecycle:{receipt.idempotency_key}"
        value = receipt.as_json()
        created = await self._store.write_state_with_audit_if_absent(
            key,
            value,
            {
                "actor": "fdai.delivery.gitops_pr.governance",
                "action_kind": "governance_pr.open_to_merge",
                "mode": Mode.SHADOW.value,
                "idempotency_key": receipt.idempotency_key,
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
        raw = await self._store.read_state(f"governance-pr-lifecycle:{idempotency_key}")
        if raw is None:
            return None
        if raw.get("schema_version") != "1.0.0":
            raise GovernancePrError("unsupported governance PR lifecycle state")
        return _decode_receipt(raw)


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
    ) -> GovernancePrLifecycleReceipt:
        action_type = _SUPPORTED.get(str(document.document.get("kind")))
        if action_type is None and document.path.startswith("rule-catalog/exemptions/"):
            action_type = "governance.grant-exemption"
        if action_type is None or document.execution_path != "pr_native" or document.applied:
            raise GovernancePrError("governance document is not an unapplied supported PR artifact")
        _require_distinct_approval(document.document)
        if not correlation_id.strip():
            raise GovernancePrError("correlation_id MUST be non-empty")
        payload = _canonical_document(document.document)
        digest = hashlib.sha256(payload).hexdigest()
        key = f"{action_type}:{digest}"
        prior = await self._lifecycle_store.load(key)
        if prior is not None:
            return prior
        patch = _yaml_document(document.document)
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
        lifecycle = GovernancePrLifecycleReceipt(
            action_type_name=action_type,
            idempotency_key=key,
            document_digest=digest,
            document_path=document.path,
            pr_ref=receipt.pr_ref,
            url=receipt.url,
            already_existed=receipt.already_existed,
            recorded_at=_rfc3339(self._clock()),
        )
        await self._lifecycle_store.save(lifecycle)
        return lifecycle


def _canonical_document(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _yaml_document(document: Mapping[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True)


def _decode_receipt(raw: Mapping[str, Any]) -> GovernancePrLifecycleReceipt:
    if raw.get("schema_version") != "1.0.0":
        raise GovernancePrError("unsupported governance PR lifecycle state")
    action_type_name = _required_text(raw, "action_type_name")
    idempotency_key = _required_text(raw, "idempotency_key")
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
    if raw.get("state") != "open" or raw.get("merge_required") is not True:
        raise GovernancePrError("governance PR lifecycle is not open-to-merge")
    if raw.get("applied") is not False or raw.get("already_existed") not in (True, False):
        raise GovernancePrError("governance PR lifecycle flags are malformed")
    recorded_at = _required_text(raw, "recorded_at")
    return GovernancePrLifecycleReceipt(
        action_type_name=action_type_name,
        idempotency_key=idempotency_key,
        document_digest=document_digest,
        document_path=document_path,
        pr_ref=pr_ref,
        url=url,
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
