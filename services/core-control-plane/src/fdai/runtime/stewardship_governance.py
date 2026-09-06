"""Restart-safe delivery of durable stewardship handover drafts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.handover import HandoverDraftArtifact
from pydantic import ValidationError

from fdai.core.stewardship.governance import (
    StewardshipGovernanceError,
    StewardshipGovernanceService,
    stewardship_idempotency_key,
)
from fdai.runtime.github_auth import github_credentials_configured
from fdai.shared.providers.remediation_pr import RemediationPrPublisher
from fdai.shared.providers.state_store import StateStore

_DRAFT_PREFIX = "handover_draft:"
_RECEIPT_PREFIX = "stewardship_governance:"
_FAILURE_PREFIX = "stewardship_governance_failure:"
_LOGGER = logging.getLogger("fdai.stewardship.governance")
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True, slots=True)
class StewardshipGovernanceWorker:
    """Publish stored handover drafts and durably record one outcome per candidate."""

    store: StateStore
    governance: StewardshipGovernanceService
    interval_seconds: float = 60.0
    batch_limit: int = 100

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("stewardship governance interval MUST be positive")
        if not 1 <= self.batch_limit <= 1000:
            raise ValueError("stewardship governance batch limit MUST be between 1 and 1000")

    async def run_once(self) -> int:
        """Publish each unseen candidate and atomically persist its Saga audit receipt."""

        processed = 0
        offset = 0
        snapshot_total: int | None = None
        while processed < self.batch_limit:
            drafts, total = await self.store.read_state_page(
                _DRAFT_PREFIX,
                limit=self.batch_limit,
                offset=offset,
            )
            if snapshot_total is None:
                snapshot_total = total
            if not drafts:
                break
            for raw in drafts:
                processed += int(await self._process(raw))
                if processed >= self.batch_limit:
                    break
            offset += len(drafts)
            if offset >= snapshot_total:
                break
        return processed

    async def _process(self, raw: Mapping[str, Any]) -> bool:
        failure_key = _failure_key(raw)
        if await self.store.read_state(failure_key) is not None:
            return False
        try:
            artifact = HandoverDraftArtifact.model_validate(_strip_legacy_computed_fields(raw))
        except ValidationError:
            return await self._record_failure(
                failure_key=failure_key,
                failure_kind="invalid_artifact",
                upload_id=None,
            )
        idempotency_key = stewardship_idempotency_key(artifact)
        receipt_digest = idempotency_key.removeprefix("stewardship-handover:")
        receipt_key = f"{_RECEIPT_PREFIX}{receipt_digest}"
        if await self.store.read_state(receipt_key) is not None:
            return False

        try:
            result = await self.governance.publish(artifact)
        except StewardshipGovernanceError:
            return await self._record_failure(
                failure_key=failure_key,
                failure_kind="invalid_candidate",
                upload_id=str(artifact.upload_id),
            )
        recorded_at = datetime.now(UTC).isoformat()
        receipt = result.receipt
        state = {
            "upload_id": str(artifact.upload_id),
            "document_id": str(artifact.document_id),
            "version_id": str(artifact.version_id),
            "idempotency_key": result.idempotency_key,
            "published": result.published,
            "reason": result.reason,
            "pr_ref": receipt.pr_ref if receipt is not None else None,
            "pr_url": receipt.url if receipt is not None else None,
            "replayed": receipt.already_existed if receipt is not None else False,
            "recorded_at": recorded_at,
        }
        return await self.store.write_state_with_audit_if_absent(
            receipt_key,
            state,
            {
                "actor": "Saga",
                "action_kind": "stewardship.governance_draft_processed",
                "upload_id": str(artifact.upload_id),
                "idempotency_key": result.idempotency_key,
                "published": result.published,
                "reason": result.reason,
                "pr_ref": receipt.pr_ref if receipt is not None else None,
                "replayed": receipt.already_existed if receipt is not None else False,
                "recorded_at": recorded_at,
            },
        )

    async def _record_failure(
        self,
        *,
        failure_key: str,
        failure_kind: str,
        upload_id: str | None,
    ) -> bool:
        recorded_at = datetime.now(UTC).isoformat()
        return await self.store.write_state_with_audit_if_absent(
            failure_key,
            {
                "failure_kind": failure_kind,
                "upload_id": upload_id,
                "recorded_at": recorded_at,
            },
            {
                "actor": "Saga",
                "action_kind": "stewardship.governance_draft_rejected",
                "failure_kind": failure_kind,
                "upload_id": upload_id,
                "recorded_at": recorded_at,
            },
        )

    async def run(self, stop: asyncio.Event) -> None:
        """Run bounded reconciliation until shutdown."""

        while not stop.is_set():
            try:
                processed = await self.run_once()
                _LOGGER.info(
                    "stewardship_governance_reconciled",
                    extra={"processed": processed},
                )
            except Exception:  # noqa: BLE001 - retry the durable batch after the interval
                _LOGGER.exception("stewardship_governance_reconciliation_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


def build_stewardship_governance_worker(
    *,
    store: StateStore,
    publisher: RemediationPrPublisher,
    environment: Mapping[str, str],
) -> StewardshipGovernanceWorker | None:
    """Compose governance delivery only when its durable GitOps prerequisites exist."""

    if not _environment_flag(environment, "FDAI_STEWARDSHIP_GOVERNANCE_ENABLED", True):
        return None
    if not github_credentials_configured(environment):
        return None
    if not environment.get("FDAI_STATE_STORE_DSN", "").strip():
        raise RuntimeError(
            "stewardship governance delivery requires FDAI_STATE_STORE_DSN "
            "when GitHub credentials are configured"
        )
    return StewardshipGovernanceWorker(
        store=store,
        governance=StewardshipGovernanceService(
            publisher=publisher,
            validation_environ=environment,
        ),
        interval_seconds=_positive_float(
            environment,
            "FDAI_STEWARDSHIP_GOVERNANCE_INTERVAL_SECONDS",
            60.0,
        ),
        batch_limit=_positive_integer(
            environment,
            "FDAI_STEWARDSHIP_GOVERNANCE_BATCH_LIMIT",
            100,
        ),
    )


def _environment_flag(
    environment: Mapping[str, str],
    key: str,
    default: bool,
) -> bool:
    raw = environment.get(key)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise RuntimeError(f"{key} MUST be a boolean value")


def _positive_float(
    environment: Mapping[str, str],
    key: str,
    default: float,
) -> float:
    raw = environment.get(key, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{key} MUST be numeric") from exc
    if value <= 0:
        raise RuntimeError(f"{key} MUST be positive")
    return value


def _positive_integer(
    environment: Mapping[str, str],
    key: str,
    default: int,
) -> int:
    raw = environment.get(key, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{key} MUST be an integer") from exc
    if not 1 <= value <= 1000:
        raise RuntimeError(f"{key} MUST be between 1 and 1000")
    return value


def _strip_legacy_computed_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Remove output-only fields written by older Pydantic serialization."""

    payload = dict(raw)
    draft_raw = payload.get("draft")
    if not isinstance(draft_raw, Mapping):
        return payload
    draft = dict(draft_raw)
    for field_name in ("mappings", "abstained"):
        items = draft.get(field_name)
        if not isinstance(items, (list, tuple)):
            continue
        cleaned_items: list[Any] = []
        for item in items:
            if not isinstance(item, Mapping):
                cleaned_items.append(item)
                continue
            cleaned = dict(item)
            person = cleaned.get("person")
            if isinstance(person, Mapping):
                cleaned_person = dict(person)
                cleaned_person.pop("unresolved", None)
                cleaned["person"] = cleaned_person
            cleaned_items.append(cleaned)
        draft[field_name] = cleaned_items
    people = draft.get("unresolved_people")
    if isinstance(people, (list, tuple)):
        cleaned_people: list[Any] = []
        for person in people:
            if isinstance(person, Mapping):
                cleaned_person = dict(person)
                cleaned_person.pop("unresolved", None)
                cleaned_people.append(cleaned_person)
            else:
                cleaned_people.append(person)
        draft["unresolved_people"] = cleaned_people
    payload["draft"] = draft
    return payload


def _failure_key(raw: Mapping[str, Any]) -> str:
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return f"{_FAILURE_PREFIX}{hashlib.sha256(serialized.encode()).hexdigest()}"


__all__ = [
    "StewardshipGovernanceWorker",
    "build_stewardship_governance_worker",
]
