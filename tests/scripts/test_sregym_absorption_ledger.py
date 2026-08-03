"""Integrity checks for the SREGym semantic absorption ledger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_LEDGER = _ROOT / "docs/internals/sregym-absorption-ledger.json"
_ALLOWED_DISPOSITIONS = {
    "semantic_port",
    "test_only_absorption",
    "superseded_verify",
    "benchmark_adapter_only",
    "reject_with_reason",
}
_ALLOWED_STATUSES = {"queued", "in_progress", "absorbed", "rejected"}


def _load() -> dict[str, Any]:
    payload = json.loads(_LEDGER.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_sregym_absorption_ledger_accounts_for_every_source_commit_once() -> None:
    ledger = _load()
    groups = ledger["groups"]
    hashes = [commit for group in groups for commit in group["commits"]]

    assert len(hashes) == ledger["source_commit_count"] == 124
    assert len(set(hashes)) == len(hashes)
    assert all(len(commit) == 40 for commit in hashes)
    digest_input = "".join(f"{commit}\n" for commit in sorted(hashes)).encode()
    assert hashlib.sha256(digest_input).hexdigest() == ledger["source_set_sha256"]


def test_sregym_absorption_ledger_uses_closed_dispositions_and_dependencies() -> None:
    ledger = _load()
    groups = ledger["groups"]
    group_ids = {group["id"] for group in groups}

    assert len(group_ids) == len(groups)
    for group in groups:
        assert group["disposition"] in _ALLOWED_DISPOSITIONS
        assert group["status"] in _ALLOWED_STATUSES
        assert group["safety_boundary"]
        assert set(group["dependencies"]) < group_ids


def test_sregym_absorption_ledger_keeps_validation_axes_independent() -> None:
    ledger = _load()

    assert ledger["validation_axes"] == [
        "benchmark_measured",
        "semantic_generalized",
        "operationalized",
        "provider_validated",
        "action_validated",
        "outcome_validated",
        "azure_validated",
    ]
    for mechanism in ledger["absorbed_mechanisms"]:
        assert all(axis in mechanism for axis in ledger["validation_axes"])
        if not mechanism["operationalized"]:
            assert mechanism["provider_validated"] is False
            assert mechanism["action_validated"] is False
            assert mechanism["outcome_validated"] is False
            assert mechanism["azure_validated"] is False
