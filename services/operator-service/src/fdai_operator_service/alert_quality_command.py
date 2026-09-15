"""Reconstruct one exact principal-bound alert request from its durable acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai_service_contracts.alert_noise_wire import AlertNoiseCommand

from fdai_operator_service.alert_quality_records import alert_quality_requester_ref

ALERT_REQUEST_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


def alert_request_ref(principal_id: str, request_key: str) -> str:
    """Use the same private namespace for admission and exact unknown-outcome lookup."""
    if ALERT_REQUEST_KEY.fullmatch(request_key) is None:
        raise ValueError("alert request key is invalid")
    raw = json.dumps(
        ["operator-alert-quality-request-v1", principal_id, request_key], separators=(",", ":")
    )
    return "alert-noise:" + hashlib.sha256(raw.encode()).hexdigest()


def command_from_record(record: Mapping[str, Any]) -> AlertNoiseCommand:
    """Resolve only authenticated acceptance fields; result data never supplies a subject."""
    outer = record.get("payload")
    if not isinstance(outer, Mapping) or not isinstance(outer.get("payload"), Mapping):
        raise ValueError("alert request body is malformed")
    body = outer["payload"]
    subject, key = record.get("principal_id"), record.get("idempotency_key")
    if not isinstance(subject, str) or not isinstance(key, str):
        raise ValueError("alert request identity missing")
    if outer.get("principal_id") != subject or outer.get("idempotency_key") != key:
        raise ValueError("alert request identity mismatch")
    if outer.get("operation") != record.get("operation"):
        raise ValueError("alert request operation mismatch")
    scope = body.get("scope_ref")
    if not isinstance(scope, str) or body.get("requester_ref") != alert_quality_requester_ref(
        subject, scope
    ):
        raise ValueError("alert request principal scope mismatch")
    accepted = datetime.fromisoformat(str(record.get("accepted_at", "")).replace("Z", "+00:00"))
    return AlertNoiseCommand.model_validate(
        {
            "operation": record["operation"],
            "request_ref": key,
            "requester_ref": body["requester_ref"],
            "scope_ref": scope,
            "requested_at": accepted,
            "expires_at": accepted + timedelta(minutes=5),
            "evidence_digest": body.get("evidence_digest"),
            "treatment": body.get("treatment"),
            "period_seconds": body.get("period_seconds"),
        }
    )
