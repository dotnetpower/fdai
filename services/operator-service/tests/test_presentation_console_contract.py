"""Guard the presentation boundary the Operator and the Console own separately.

The Operator never runs the Console parser and the Console never sees a real
Operator artifact, so a slot, kind, or bound that drifts apart is invisible to
both suites: the Console silently discards the whole artifact and the card
disappears. This reads the Console's own allowlist and bounds out of its source
and checks every artifact the Operator emits against them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_presentation_artifact,
)
from fdai_service_contracts import JsonObject

_PARSER = (
    Path(__file__).resolve().parents[3] / "console/src/deck/presentation-artifact.ts"
).read_text(encoding="utf-8")


def _console_bound(name: str) -> int:
    match = re.search(rf"^const {name} = (\d+);", _PARSER, re.MULTILINE)
    assert match is not None, f"the Console no longer declares {name}"
    return int(match.group(1))


def _console_slot_kinds() -> dict[str, set[str]]:
    block = re.search(
        r"const SLOT_KINDS: Readonly<Record<string, ReadonlySet<.*?>>> = \{(.*?)\n\};",
        _PARSER,
        re.DOTALL,
    )
    assert block is not None, "the Console no longer declares SLOT_KINDS"
    slots: dict[str, set[str]] = {}
    for slot_id, kinds in re.findall(r"(\w+): new Set\(\[(.*?)\]\)", block.group(1)):
        slots[slot_id] = set(re.findall(r'"([^"]+)"', kinds))
    assert slots, "no Console slot definitions were parsed"
    return slots


MAX_BLOCKS = _console_bound("MAX_BLOCKS")
MAX_ITEMS = _console_bound("MAX_ITEMS")
MAX_REFS = _console_bound("MAX_REFS")
SLOT_KINDS = _console_slot_kinds()

_EVIDENCE_REFS = ["ontology-function:logic-invocation:abc123"]


def _incident_details(*, records: int, verified: int, gaps: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "semantic_query_outputs",
        "outputs": [
            {
                "incident_profile": {"status": "triaging"},
                "correlated_evidence": [
                    {"audit_ref": f"audit:{index}"} for index in range(records)
                ],
                "verified_records": verified,
                "evidence_gaps": gaps,
                "causal_assessment": {"status": "not_available"},
            }
        ],
    }


def _general_details() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "semantic_query_outputs",
        "outputs": [
            {
                "node_id": "resources",
                "rows": [{"row_id": "r1", "values": {"resource.name": "vm-a"}}],
                "returned_rows": 1,
                "total_rows": 3,
            }
        ],
    }


def _assert_console_accepts(artifact: JsonObject) -> None:
    blocks = cast(list[dict[str, Any]], artifact["blocks"])
    assert 0 < len(blocks) <= MAX_BLOCKS
    assert 0 < len(cast(list[str], artifact["evidence_refs"])) <= MAX_REFS
    seen: set[str] = set()
    for block in blocks:
        slot_id = cast(str, block["slot_id"])
        kind = cast(str, block["kind"])
        assert slot_id in SLOT_KINDS, f"Operator emits slot {slot_id!r} the Console would reject"
        assert kind in SLOT_KINDS[slot_id], (
            f"Operator emits kind {kind!r} in slot {slot_id!r} the Console would reject"
        )
        assert slot_id not in seen, f"the Console rejects a repeated slot {slot_id!r}"
        seen.add(slot_id)
        data = cast(dict[str, Any], block["data"])
        if kind == "summary":
            items = cast(list[dict[str, Any]], data["items"])
            assert set(data) == {"items"}
            assert 0 < len(items) <= MAX_ITEMS
            for item in items:
                assert set(item) == {"label", "value", "tone"}
                assert isinstance(item["value"], str) and item["value"]
        elif kind == "callout":
            lines = cast(list[str], data["lines"])
            assert set(data) == {"tone", "lines"}
            assert 0 < len(lines) <= MAX_ITEMS
            assert len(set(lines)) == len(lines), "the Console rejects repeated callout lines"
        elif kind in {"table", "list", "threshold_table"}:
            assert set(data) == {"columns", "rows", "status_key"}


@pytest.mark.parametrize("locale", ["en", "ko"])
@pytest.mark.parametrize(
    "details",
    [
        _incident_details(records=1, verified=1, gaps=[]),
        _incident_details(records=20, verified=31, gaps=["correlated_audit_truncated"]),
        _incident_details(
            records=20,
            verified=200,
            gaps=[
                "impact_evidence_missing",
                "grounded_citations_missing",
                "incident_profile_missing",
                "correlated_audit_truncated",
            ],
        ),
        _general_details(),
    ],
)
def test_every_emitted_artifact_stays_inside_the_console_contract(
    details: dict[str, Any],
    locale: str,
) -> None:
    artifact = semantic_presentation_artifact(
        semantic={"evidence_refs": _EVIDENCE_REFS},
        technical_details=details,
        locale=locale,
    )

    assert artifact is not None
    _assert_console_accepts(artifact)
