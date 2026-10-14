"""Request-pinned, bounded what-if delivery with at-least-once crash recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from fdai.agents._framework.outbox_publication import (
    PublicationClaim,
    claim_expired,
    claim_matches,
    new_publication_claim_owner,
    publish_claimed_outbox,
)
from fdai.agents._framework.topics import stable_idempotency_key

PUBLICATION_WINDOW_KEY = "pantheon/forseti/what-if-publications/v1"
MAX_PUBLICATIONS = 512
MAX_WINDOW_BYTES = 524288
PUBLICATION_LEASE = timedelta(seconds=4)
_ROW_FIELDS = frozenset(
    {"request_key", "payload", "payload_digest", "status", "claim_owner", "claimed_at"}
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _decode(raw: Any) -> tuple[int, list[dict[str, Any]]]:
    if raw is None:
        return 0, []
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"kind", "revision", "records", "execution_authority"}
        or raw["kind"] != "forseti_what_if_publications_v1"
        or type(raw["revision"]) is not int
        or raw["revision"] < 1
        or raw["execution_authority"] is not False
        or not isinstance(raw["records"], list)
        or len(raw["records"]) > MAX_PUBLICATIONS
        or len(_canonical(raw).encode("utf-8")) > MAX_WINDOW_BYTES
    ):
        raise ValueError("Forseti what-if publication window is malformed")
    seen: set[str] = set()
    for row in raw["records"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != _ROW_FIELDS
            or not isinstance(row["request_key"], str)
            or not row["request_key"]
            or len(row["request_key"]) > 512
            or row["request_key"] in seen
            or row["status"] not in {"pending", "publishing", "published"}
            or not isinstance(row["claim_owner"], str)
            or len(row["claim_owner"]) > 128
            or not isinstance(row["claimed_at"], str)
            or len(row["claimed_at"]) > 64
            or not isinstance(row["payload"], dict)
            or row["payload_digest"] != _digest(row["payload"])
        ):
            raise ValueError("Forseti what-if publication record is malformed")
        payload = row["payload"]
        if (
            set(payload)
            != {
                "producer_principal",
                "kind",
                "correlation_id",
                "resource_id",
                "action_type",
                "risk_verdict",
                "resolved_autonomy_ceiling",
                "reason",
                "quorum_required",
                "what_if_contract",
                "outcomes",
                "disagreement_count",
                "idempotency_key",
            }
            or payload.get("resource_id") != "retrospective-what-if"
            or payload.get("reason") != "retrospective_what_if_evidence"
            or type(payload.get("quorum_required")) is not int
            or payload["quorum_required"] != 1
            or not isinstance(payload.get("correlation_id"), str)
            or not payload["correlation_id"]
            or len(payload["correlation_id"]) > 512
            or not isinstance(payload.get("what_if_contract"), dict)
            or type(payload.get("disagreement_count")) is not int
            or not 0 <= payload["disagreement_count"] <= 32
            or payload.get("producer_principal") != "Forseti"
            or payload.get("kind") != "retrospective_what_if"
            or payload.get("action_type") != ""
            or payload.get("risk_verdict") != "hil"
            or payload.get("resolved_autonomy_ceiling") != "shadow_only"
            or not isinstance(payload.get("outcomes"), list)
            or not 1 <= len(payload["outcomes"]) <= 32
            or not isinstance(payload.get("idempotency_key"), str)
            or not payload["idempotency_key"]
        ):
            raise ValueError("Forseti what-if publication lost its inert contract")
        contract = payload["what_if_contract"]
        if (
            set(contract)
            != {
                "contract_version",
                "active_judgment_table_digest",
                "what_if_judgment_table_digest",
                "sample_limit",
                "selection",
            }
            or contract["contract_version"] != "retrospective-what-if.v1"
            or contract["selection"] != "recent_retained_judgment_inputs"
            or type(contract["sample_limit"]) is not int
            or not 1 <= contract["sample_limit"] <= 32
            or not isinstance(contract["what_if_judgment_table_digest"], str)
            or row["request_key"]
            != stable_idempotency_key(
                "forseti-what-if-request",
                payload["correlation_id"],
                contract["what_if_judgment_table_digest"],
                contract["sample_limit"],
            )
        ):
            raise ValueError("Forseti what-if publication request binding is invalid")
        if row["status"] == "publishing":
            claimed_at = datetime.fromisoformat(row["claimed_at"])
            if not row["claim_owner"] or claimed_at.utcoffset() is None:
                raise ValueError("Forseti what-if publication claim is malformed")
        elif row["claim_owner"] or row["claimed_at"]:
            raise ValueError("Forseti what-if inactive publication has a claim")
        seen.add(row["request_key"])
    return raw["revision"], deepcopy(raw["records"])


async def frozen_publication(host: Any, request_key: str) -> dict[str, Any] | None:
    if host._forseti_state_store is None:
        return None
    async with asyncio.timeout(2):
        _revision, rows = _decode(
            await host._forseti_state_store.read_state(PUBLICATION_WINDOW_KEY)
        )
    return next((row for row in rows if row["request_key"] == request_key), None)


async def _update(host: Any, change: Callable[[list[dict[str, Any]]], Any]) -> Any:
    store = host._forseti_state_store
    async with asyncio.timeout(2):
        for _attempt in range(8):
            revision, rows = _decode(await store.read_state(PUBLICATION_WINDOW_KEY))
            result = change(rows)
            if result is None:
                return None
            payload = {
                "kind": "forseti_what_if_publications_v1",
                "revision": revision + 1,
                "records": rows,
                "execution_authority": False,
            }
            while (
                len(rows) > MAX_PUBLICATIONS
                or len(_canonical(payload).encode("utf-8")) > MAX_WINDOW_BYTES
            ):
                completed = next((row for row in rows if row["status"] == "published"), None)
                if completed is None:
                    raise RuntimeError("Forseti what-if publication window has no free slot")
                rows.remove(completed)
            _decode(payload)
            if revision == 0:
                accepted = await store.write_state_if_absent(PUBLICATION_WINDOW_KEY, payload)
            else:
                accepted = await store.compare_and_set_state(
                    PUBLICATION_WINDOW_KEY, payload, expected_revision=revision
                )
            if accepted:
                return result
    raise RuntimeError("Forseti what-if publication CAS contention exceeded its bound")


async def publish_comparison(
    host: Any, request_key: str, candidate_payload: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    def claim(rows: list[dict[str, Any]]) -> tuple[PublicationClaim, dict[str, Any]] | None:
        row = next((row for row in rows if row["request_key"] == request_key), None)
        if row is None:
            if len(rows) >= MAX_PUBLICATIONS:
                completed = next((entry for entry in rows if entry["status"] == "published"), None)
                if completed is None:
                    raise RuntimeError("Forseti what-if publication window has no free slot")
                rows.remove(completed)
            row = {
                "request_key": request_key,
                "payload": deepcopy(candidate_payload),
                "payload_digest": _digest(candidate_payload),
                "status": "pending",
                "claim_owner": "",
                "claimed_at": "",
            }
            rows.append(row)
        now = host._test_context_clock()
        if row["status"] == "published" or (
            row["status"] == "publishing"
            and not claim_expired(claimed_at=row["claimed_at"], now=now, lease=PUBLICATION_LEASE)
        ):
            return None
        active_claim = PublicationClaim(
            owner=new_publication_claim_owner("Forseti"), claimed_at=now.isoformat()
        )
        row.update(
            status="publishing", claim_owner=active_claim.owner, claimed_at=active_claim.claimed_at
        )
        return active_claim, deepcopy(row["payload"])

    async def finalize(active_claim: PublicationClaim, status: str) -> bool:
        def advance(rows: list[dict[str, Any]]) -> bool | None:
            row = next((row for row in rows if row["request_key"] == request_key), None)
            if row is None or row["status"] != "publishing" or not claim_matches(row, active_claim):
                return None
            row.update(status=status, claim_owner="", claimed_at="")
            return True

        return (await _update(host, advance)) is True

    async def release(active_claim: PublicationClaim) -> None:
        await finalize(active_claim, "pending")

    async with asyncio.timeout(8):
        claimed = await _update(host, claim)
        if claimed is None:
            return False, candidate_payload
        active_claim, payload = claimed
        published = await publish_claimed_outbox(
            active_claim,
            publish=lambda: host.bus.publish("Forseti", "object.verdict", payload),
            mark_published=lambda token: finalize(token, "published"),
            release=release,
            lease=PUBLICATION_LEASE,
        )
    return published, payload


async def recover_comparisons(host: Any) -> int:
    if host._forseti_state_store is None or host.bus is None:
        return 0
    published = 0
    async with asyncio.timeout(15):
        async with asyncio.timeout(2):
            _revision, rows = _decode(
                await host._forseti_state_store.read_state(PUBLICATION_WINDOW_KEY)
            )
        now = host._test_context_clock()
        eligible = [
            row
            for row in rows
            if row["status"] == "pending"
            or (
                row["status"] == "publishing"
                and claim_expired(claimed_at=row["claimed_at"], now=now, lease=PUBLICATION_LEASE)
            )
        ]
        for row in eligible[:16]:
            try:
                accepted, _payload = await publish_comparison(
                    host, row["request_key"], row["payload"]
                )
            except Exception:
                host.record_behavior("retrospective_what_if:publication_recovery_failed")
                continue
            published += int(accepted)
    return published
