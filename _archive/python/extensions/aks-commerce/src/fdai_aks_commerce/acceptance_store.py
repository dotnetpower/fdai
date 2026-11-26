"""Immutable, audit-backed order-acceptance observations over the existing state-store port."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime
from typing import Any

from fdai.shared.providers.state_store import StateStore
from pydantic import TypeAdapter

from fdai_aks_commerce.acceptance import (
    OrderAcceptanceEvidence,
    OrderAcceptanceIntent,
    OrderAcceptanceProbe,
    evaluate_order_acceptance,
)
from fdai_aks_commerce.acceptance_receipts import (
    RECEIPT_PREFIX,
    StoredOrderAcceptanceReceiptVerifier,
)

_PREFIX = "aks-commerce:acceptance-observation:v1:"
_EVIDENCE_ADAPTER = TypeAdapter(OrderAcceptanceEvidence)
_EVIDENCE_FIELDS = {field.name for field in fields(OrderAcceptanceEvidence)}
_PROBE_FIELDS = {field.name for field in fields(OrderAcceptanceProbe)}


class StoredOrderAcceptanceSource:
    """Read the newest bounded observation for an exact target and policy; no trust fallback."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def observe(self, intent: OrderAcceptanceIntent) -> OrderAcceptanceEvidence | None:
        """Decode retained observations strictly; invalid or partial writes remain unavailable."""
        records = await self._store.read_states(_prefix(intent), limit=10)
        observations: list[OrderAcceptanceEvidence] = []
        for record in records:
            if set(record) != {"policy_ref", "evidence_digest", "evidence"}:
                raise ValueError("stored acceptance observation fields are invalid")
            if record["policy_ref"] != intent.policy_ref:
                raise ValueError("stored acceptance policy does not match")
            evidence = decode_acceptance_evidence(record["evidence"])
            assessment = evaluate_order_acceptance(
                intent,
                evidence,
                now=evidence.observed_at,
                window_seconds=intent.max_age_seconds,
            )
            if assessment.evidence_digest != record["evidence_digest"]:
                raise ValueError("stored acceptance observation digest does not match")
            observations.append(evidence)
        return max(observations, key=lambda item: item.observed_at) if observations else None


async def retain_order_acceptance(
    *,
    store: StateStore,
    verifier: StoredOrderAcceptanceReceiptVerifier,
    intent: OrderAcceptanceIntent,
    evidence: OrderAcceptanceEvidence,
    receipt: Mapping[str, Any],
    now: datetime,
) -> str:
    """Persist signed observations with atomic per-record audit and conflict detection.

    A receipt is retained before its observation. Partial failure exposes no unsigned observation;
    the analyzer revalidates current trust at use time. Issuance and source authorization are owned
    by the separate observer, not this ingestion function.
    """
    assessment = evaluate_order_acceptance(
        intent,
        evidence,
        now=now,
        window_seconds=intent.max_age_seconds,
    )
    if assessment.status == "held":
        raise ValueError("unqualified acceptance observations cannot enter operational storage")
    if receipt.get("authorization_refs") != sorted(
        {probe.authorization_ref for probe in evidence.probes}
    ):
        raise ValueError("acceptance receipt does not bind the probe authorization references")
    if not await verifier.verify_record(
        receipt,
        verification_ref=evidence.verification_ref,
        evidence_digest=assessment.evidence_digest,
    ):
        raise ValueError("acceptance observation receipt is not authenticated")
    await _write_once(store, RECEIPT_PREFIX + evidence.verification_ref, dict(receipt), now)
    record = {
        "policy_ref": intent.policy_ref,
        "evidence_digest": assessment.evidence_digest,
        "evidence": _EVIDENCE_ADAPTER.dump_python(evidence, mode="json"),
    }
    await _write_once(store, _prefix(intent) + assessment.evidence_digest, record, now)
    return assessment.evidence_digest


def decode_acceptance_evidence(value: object) -> OrderAcceptanceEvidence:
    """Parse the closed JSON representation without coercing unknown states into values."""
    if not isinstance(value, dict) or set(value) != _EVIDENCE_FIELDS:
        raise ValueError("acceptance observation fields are invalid")
    probes = value.get("probes")
    if (
        not isinstance(probes, list)
        or len(probes) > 10
        or any(not isinstance(probe, dict) or set(probe) != _PROBE_FIELDS for probe in probes)
    ):
        raise ValueError("acceptance probe records are invalid")
    return _EVIDENCE_ADAPTER.validate_json(json.dumps(value, allow_nan=False), strict=True)


def _prefix(intent: OrderAcceptanceIntent) -> str:
    identity = json.dumps(
        [intent.policy_ref, intent.cluster_ref, intent.resource_ref], separators=(",", ":")
    )
    return _PREFIX + hashlib.sha256(identity.encode()).hexdigest() + ":"


async def _write_once(store: StateStore, key: str, value: dict[str, Any], now: datetime) -> None:
    inserted = await store.write_state_with_audit_if_absent(
        key,
        value,
        {
            "event": "aks_commerce.acceptance_evidence_retained",
            "record_key": key,
            "occurred_at": now.isoformat(),
            "execution_authority": False,
        },
    )
    if not inserted and await store.read_state(key) != value:
        raise ValueError("acceptance immutable record conflicts with retained evidence")
