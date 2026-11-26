"""Atomic source and target conflict transitions for Assurance Twin evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.delivery.assurance_twin_evidence_codec import (
    source_conflict_audit as _source_conflict_audit,
)
from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest
from fdai.shared.providers.state_store import AssuranceTwinConfirmationStore, StateStore

_PREFIX = "runtime:assurance-twin-evidence:"


class AssuranceTwinEvidenceConflictMixin:
    """Provide bounded atomic conflict transitions to the durable repository."""

    _store: StateStore

    async def mark_inventory_superseded(
        self,
        request: AssuranceTwinPublishRequest,
    ) -> bool:
        raise NotImplementedError

    async def mark_inventory_changed(
        self,
        request: AssuranceTwinPublishRequest,
    ) -> bool:
        """Terminalize pending evidence or atomically revoke a confirmed target."""

        source_key = _state_key(request)
        if not isinstance(self._store, AssuranceTwinConfirmationStore):
            raise RuntimeError("Assurance Twin Inventory conflict store is unavailable")
        target_key = _target_key(request)
        for _attempt in range(8):
            source = await self._store.read_state(source_key)
            if source is None:
                return False
            if source.get("conflict") is True:
                return True
            if source.get("writer_status") != "confirmed":
                return await self.mark_inventory_superseded(request)
            source_revision = _revision(source, "retained evidence")
            conflicted_source = {
                **dict(source),
                "revision": source_revision + 1,
                "request_status": "conflict",
                "writer_status": "conflict",
                "conflict": True,
                "inventory_revision_changed": True,
            }
            target = await self._store.read_state(target_key)
            target_value: Mapping[str, Any] | None = None
            target_revision: int | None = None
            if (
                target is not None
                and target.get("conflict") is None
                and target.get("evidence_source_revision") == request.source_revision
                and target.get("evidence_digest") == source.get("evidence_digest")
            ):
                target_revision = _revision(target, "target")
                target_value = {
                    **dict(target),
                    "revision": target_revision + 1,
                    "source_confirmed": False,
                    "publication_outbox": None,
                    "conflict": {
                        "reason_code": "assurance_twin_inventory_revision_changed",
                        "stored_evidence_digest": target.get("evidence_digest"),
                        "rejected_evidence_digest": target.get("evidence_digest"),
                    },
                }
            if await self._store.conflict_assurance_twin_source(
                source_key=source_key,
                source_value=conflicted_source,
                expected_source_revision=source_revision,
                target_key=target_key,
                target_value=target_value,
                expected_target_revision=target_revision,
                audit_entry={
                    "kind": "assurance_twin_inventory_revision_changed",
                    "producer_principal": ("Heimdall" if request.kind == "posture" else "Forseti"),
                    "idempotency_key": request.idempotency_key,
                    "source_revision": request.source_revision,
                    "execution_authority": False,
                },
            ):
                return True
        return False

    async def _resolve_source_conflict(
        self,
        *,
        request: AssuranceTwinPublishRequest,
        retained: Mapping[str, Any],
        incoming: Mapping[str, Any],
    ) -> AssuranceTwinPublishRequest:
        if not isinstance(self._store, AssuranceTwinConfirmationStore):
            raise RuntimeError("Assurance Twin source conflict store is unavailable")
        key = _state_key(request)
        current = retained
        for _attempt in range(3):
            if current.get("conflict") is True:
                raise ValueError("Assurance Twin retained evidence identity conflict")
            revision = _revision(current, "retained evidence")
            conflicted = {
                **dict(current),
                "revision": revision + 1,
                "request_status": "conflict",
                "writer_status": "conflict",
                "conflict": True,
                "conflicting_evidence_digest": incoming.get("evidence_digest"),
            }
            target_key = _target_key(request)
            target = await self._store.read_state(target_key)
            target_value: Mapping[str, Any] | None = None
            target_revision: int | None = None
            if target is not None and target.get("conflict") is None:
                source_record = current.get("record")
                source_generated = (
                    source_record.get("generated_at")
                    if isinstance(source_record, Mapping)
                    else None
                )
                target_generated = target.get("generated_at")
                if (
                    isinstance(source_generated, str)
                    and isinstance(target_generated, str)
                    and datetime.fromisoformat(target_generated)
                    <= datetime.fromisoformat(source_generated)
                ):
                    target_revision = _revision(target, "target")
                    target_value = {
                        **dict(target),
                        "revision": target_revision + 1,
                        "source_confirmed": False,
                        "publication_outbox": None,
                        "conflict": {
                            "reason_code": (
                                "assurance_twin_posture_timestamp_conflict"
                                if request.kind == "posture"
                                else "assurance_twin_review_key_conflict"
                            ),
                            "stored_evidence_digest": target.get("evidence_digest"),
                            "rejected_evidence_digest": incoming.get("evidence_digest"),
                        },
                    }
            applied = await self._store.conflict_assurance_twin_source(
                source_key=key,
                source_value=conflicted,
                expected_source_revision=revision,
                target_key=target_key,
                target_value=target_value,
                expected_target_revision=target_revision,
                audit_entry=_source_conflict_audit(request, incoming),
            )
            if applied and await self._store.read_state(key) == conflicted:
                raise ValueError("Assurance Twin retained evidence identity conflict")
            reread = await self._store.read_state(key)
            if reread is None:
                raise RuntimeError("Assurance Twin source conflict record disappeared")
            current = reread
        raise RuntimeError("Assurance Twin source conflict exceeded its retry bound")


def _state_key(request: AssuranceTwinPublishRequest) -> str:
    return f"{_PREFIX}{request.idempotency_key.removeprefix('sha256:')}"


def _target_key(request: AssuranceTwinPublishRequest) -> str:
    return (
        f"runtime:assurance-twin-posture:{request.source_key}"
        if request.kind == "posture"
        else f"runtime:assurance-twin-review:{request.source_key}"
    )


def _revision(value: Mapping[str, Any], name: str) -> int:
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError(f"Assurance Twin {name} revision is invalid")
    return revision


__all__ = ["AssuranceTwinEvidenceConflictMixin"]
