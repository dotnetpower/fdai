"""Tests for fail-closed diagnostic ledger validation."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fdai.core.ontology_platform.diagnostic_ledger import validate_diagnostic_ledger

_ROOT = Path(__file__).resolve().parents[5]


def _ledger() -> dict[str, Any]:
    return json.loads(
        (_ROOT / "docs/internals/sregym-absorption-ledger.json").read_text(encoding="utf-8")
    )


def test_accepts_complete_frozen_ledger() -> None:
    ledger = validate_diagnostic_ledger(_ledger())

    assert len(ledger.mechanisms) == 61
    assert len(ledger.source_set_sha256) == 64


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(schema_version="2.0.0"),
        lambda value: value.update(validation_axes=["benchmark_measured"]),
        lambda value: value.update(source_set_sha256="0" * 64),
        lambda value: value.update(source_head=value["groups"][0]["commits"][0]),
        lambda value: value.update(archive_bundle_sha256="0" * 64),
        lambda value: value["groups"][0]["commits"].append(value["groups"][0]["commits"][0]),
        lambda value: value["absorbed_mechanisms"][0].update(status="action_eligible"),
        lambda value: value["absorbed_mechanisms"][0]["source_commits"].append(
            value["absorbed_mechanisms"][0]["source_commits"][0]
        ),
        lambda value: value["absorbed_mechanisms"][0].update(source_commits=["z" * 40]),
    ),
)
def test_rejects_schema_provenance_and_status_drift(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(_ledger())
    mutate(payload)

    with pytest.raises(ValueError):
        validate_diagnostic_ledger(payload)
