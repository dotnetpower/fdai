"""Bounded durable comparison inputs, not complete historical execution context."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict

QUALITY_WINDOW_KEY = "pantheon/forseti/quality-input-window/v1"
MAX_QUALITY_INPUTS = 512
_FIELDS = frozenset({"event_type", "action_type", "risk_verdict", "judgment_table_digest", "tier"})


def _sample_digest(key: str, sample: Mapping[str, str]) -> str:
    encoded = json.dumps(
        {"key": key, "sample": dict(sample)}, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decode(raw: Any) -> tuple[int, list[dict[str, Any]]]:
    if raw is None:
        return 0, []
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"kind", "revision", "records", "execution_authority"}
        or raw["kind"] != "forseti_quality_window_v1"
        or raw["execution_authority"] is not False
        or type(raw["revision"]) is not int
        or raw["revision"] < 1
        or not isinstance(raw["records"], list)
        or len(raw["records"]) > MAX_QUALITY_INPUTS
    ):
        raise ValueError("Forseti quality window is malformed")
    records = raw["records"]
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {"key", "sample", "sample_digest"}:
            raise ValueError("Forseti quality record is malformed")
        key, sample = record["key"], record["sample"]
        if (
            not isinstance(key, str)
            or not key
            or key != key.strip()
            or len(key) > 512
            or key in seen
            or not isinstance(sample, Mapping)
            or set(sample) != _FIELDS
            or any(not isinstance(value, str) or len(value) > 512 for value in sample.values())
            or sample["tier"] not in {"T0", "T1", "T2"}
            or sample["risk_verdict"] not in {"", "auto", "hil", "deny"}
        ):
            raise ValueError("Forseti quality sample is malformed")
        digest = sample["judgment_table_digest"]
        if digest and (
            not digest.startswith("sha256:")
            or len(digest) != 71
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            raise ValueError("Forseti quality source digest is malformed")
        if record["sample_digest"] != _sample_digest(key, sample):
            raise ValueError("Forseti quality sample content was substituted")
        seen.add(key)
    return raw["revision"], [dict(record) for record in records]


async def retain_quality_sample(host: Any, key: str, sample: Mapping[str, str]) -> None:
    store = host._forseti_state_store
    if store is None:
        return
    async with asyncio.timeout(2):
        for _attempt in range(8):
            revision, records = _decode(await store.read_state(QUALITY_WINDOW_KEY))
            entry = {
                "key": key,
                "sample": dict(sample),
                "sample_digest": _sample_digest(key, sample),
            }
            existing = next((record for record in records if record["key"] == key), None)
            if existing is not None:
                if existing != entry:
                    raise ValueError("Forseti quality input identity was substituted")
                return
            payload = {
                "kind": "forseti_quality_window_v1",
                "revision": revision + 1,
                "records": [*records, entry][-MAX_QUALITY_INPUTS:],
                "execution_authority": False,
            }
            _decode(payload)
            if revision == 0:
                accepted = await store.write_state_if_absent(QUALITY_WINDOW_KEY, payload)
            else:
                accepted = await store.compare_and_set_state(
                    QUALITY_WINDOW_KEY,
                    payload,
                    expected_revision=revision,
                )
            if accepted:
                return
    raise RuntimeError("Forseti quality window CAS contention exceeded its bound")


async def restore_quality_samples(host: Any) -> int:
    store = host._forseti_state_store
    if store is None:
        return 0
    async with asyncio.timeout(2):
        _revision, records = _decode(await store.read_state(QUALITY_WINDOW_KEY))
    host._verdict_quality_samples = BoundedLruDict(MAX_QUALITY_INPUTS)
    for record in records:
        host._verdict_quality_samples.set(record["key"], dict(record["sample"]))
    return len(records)
