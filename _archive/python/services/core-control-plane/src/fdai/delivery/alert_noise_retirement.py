"""Retire unpublishable alert-noise outbox rows by exact key with an audit record.

A retained result that fails the current contract is never published, rewritten as a current
result, or deleted. An authenticated unreleased 1.0.0 result is retired as a legacy record, and any
other invalid row is retired as invalid. A row that can't be addressed exactly keeps its content
and receives one deduplicated audited denial for human repair.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.alert_noise import Ref
from fdai_service_contracts.alert_noise_legacy import (
    LEGACY_ALERT_CONTRACT_REASON,
    LEGACY_ALERT_CONTRACT_VERSION,
    decode_legacy_alert_result,
)
from fdai_service_contracts.ontology_query import content_digest
from pydantic import TypeAdapter, ValidationError

from fdai.shared.providers.state_store import StateStore

ALERT_RESULT_PREFIX = "alert-noise:result:"
INVALID_RESULT_REASON = "invalid_result_record"
_DENIAL_PREFIX = "alert-noise:result-retirement-denied:"
_REF: TypeAdapter[str] = TypeAdapter(Ref)
_LOGGER = logging.getLogger(__name__)


def _request_ref(raw: object) -> str | None:
    command = raw.get("command") if isinstance(raw, Mapping) else None
    value = command.get("request_ref") if isinstance(command, Mapping) else None
    try:
        return _REF.validate_python(value)
    except ValidationError:
        return None


async def retire_unpublishable_result(store: StateStore, row: Mapping[str, Any]) -> bool:
    """Retire one pending row the current contract rejects; return whether it was retired."""
    raw = row.get("result")
    try:
        legacy = decode_legacy_alert_result(raw)
    except ValueError:
        legacy = None
    reason = LEGACY_ALERT_CONTRACT_REASON if legacy is not None else INVALID_RESULT_REASON
    request_ref = legacy.command.request_ref if legacy is not None else _request_ref(raw)
    record_digest = content_digest(dict(row))
    audit = {
        "actor": "Forseti",
        "action_kind": "alert_noise.result.retired",
        "correlation_id": request_ref or record_digest,
        "reason": reason,
        "record_digest": record_digest,
        "retired_schema_version": LEGACY_ALERT_CONTRACT_VERSION if legacy is not None else None,
        "execution_authority": False,
    }
    revision = row.get("revision")
    if request_ref is not None and type(revision) is int:
        key = ALERT_RESULT_PREFIX + request_ref
        # Only the exact retained row may change state; a claimed key must hold this content.
        if await store.read_state(key) == row:
            return await store.compare_and_set_state_with_audit(
                key,
                {**row, "publication_state": "retired", "revision": revision + 1},
                expected_revision=revision,
                audit_entry=audit,
            )
    denied = await store.write_state_with_audit_if_absent(
        _DENIAL_PREFIX + record_digest,
        {"reason": reason, "record_digest": record_digest, "execution_authority": False},
        {**audit, "action_kind": "alert_noise.result.retirement_denied"},
    )
    if denied:
        _LOGGER.warning(
            "alert_noise_result_unaddressable",
            extra={"record_digest": record_digest, "reason": reason},
        )
    return False


__all__ = [
    "ALERT_RESULT_PREFIX",
    "INVALID_RESULT_REASON",
    "retire_unpublishable_result",
]
