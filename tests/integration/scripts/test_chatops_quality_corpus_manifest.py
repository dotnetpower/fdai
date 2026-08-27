"""Tests for the content-free hidden ChatOps corpus manifest."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
)
from scripts.evaluation.chatops_quality_corpus_manifest import (
    CorpusManifestError,
    main,
    parse_manifest,
    summary,
)

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "evaluation"
    / "chatops_quality_corpus_manifest.py"
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _raw() -> dict[str, Any]:
    contract = CHATOPS_QUALITY_CONTRACT_V1
    cases: list[dict[str, object]] = []
    for locale in ("en", "ko"):
        local_index = 0
        for conversation_index in range(75):
            for turn_index in (1, 2):
                tags = ["multi_turn"]
                if local_index < 50:
                    tags.insert(0, "adversarial_ambiguous")
                if local_index < 75:
                    tags.append("sre_incident_rca")
                if local_index < 50:
                    tags.append("action_channel_attachment")
                case_id = f"{locale}-case-{local_index:03d}"
                cases.append(
                    {
                        "case_id": case_id,
                        "conversation_id": (f"{locale}-conversation-{conversation_index:03d}"),
                        "turn_index": turn_index,
                        "locale": locale,
                        "content_commitment": _digest(f"content-{case_id}"),
                        "label_commitment": _digest(f"label-{case_id}"),
                        "tags": tags,
                        "rubric_item_ids": list(range(1, 51)),
                    }
                )
                local_index += 1
        for single_index in range(100):
            tags = []
            if local_index < 200:
                tags.append("adversarial_ambiguous")
            if local_index < 225:
                tags.append("sre_incident_rca")
            if local_index < 200:
                tags.append("action_channel_attachment")
            case_id = f"{locale}-case-{local_index:03d}"
            cases.append(
                {
                    "case_id": case_id,
                    "conversation_id": f"{locale}-single-{single_index:03d}",
                    "turn_index": 1,
                    "locale": locale,
                    "content_commitment": _digest(f"content-{case_id}"),
                    "label_commitment": _digest(f"label-{case_id}"),
                    "tags": tags,
                    "rubric_item_ids": list(range(1, 51)),
                }
            )
            local_index += 1
    return {
        "schema_version": 1,
        "corpus_id": "chatops-hidden",
        "corpus_version": "v1",
        "frozen_at": "2026-08-27T00:00:00Z",
        "freeze_revision": "a" * 40,
        "qualification_contract_version": contract.version,
        "qualification_contract_digest": contract.content_digest,
        "restricted_artifact_id": "hidden-artifact-v1",
        "hidden_payload_digest": "b" * 64,
        "review_protocol": {
            "labeling_protocol_version": "labeling-v1",
            "evaluator_set_version": "evaluators-v1",
            "run_configuration_version": "runtime-v1",
            "confidence_method": "predeclared-binomial-v1",
            "confidence_level": 0.95,
            "minimum_point_success_rate": 0.98,
            "minimum_independent_raters": 2,
            "minimum_rater_agreement": 0.8,
            "tie_break_protocol_version": "tie-break-v1",
            "minimum_runs": 3,
        },
        "rubric_observation_floors": {str(item_id): 500 for item_id in range(1, 51)},
        "cases": cases,
    }


def test_validates_balanced_coverage_and_returns_content_free_summary() -> None:
    manifest = parse_manifest(_raw())

    receipt = summary(manifest)

    assert receipt["turn_count"] == 500
    assert receipt["locales"] == {"en": 250, "ko": 250}
    assert receipt["multi_turn_conversations"] == 150
    assert receipt["tagged_turns"] == {
        "adversarial_ambiguous": 200,
        "sre_incident_rca": 300,
        "action_channel_attachment": 200,
    }
    assert set(receipt["rubric_observation_counts"].values()) == {500}
    assert len(receipt["content_digest"]) == 64
    rendered = json.dumps(receipt)
    assert "case-000" not in rendered
    assert "label-" not in rendered


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda raw: raw.update({"unexpected": True}),
            "fields differ",
        ),
        (
            lambda raw: raw["cases"].pop(),
            "at least 500 turns",
        ),
        (
            lambda raw: raw["review_protocol"].update({"minimum_rater_agreement": 0.79}),
            "minimum_rater_agreement",
        ),
        (
            lambda raw: raw["review_protocol"].update({"minimum_runs": 2}),
            "minimum_runs",
        ),
        (
            lambda raw: raw["rubric_observation_floors"].pop("50"),
            "item ids 1 through 50",
        ),
        (
            lambda raw: raw["cases"][0].update({"rubric_item_ids": list(range(1, 50))}),
            "rubric observation floors",
        ),
        (
            lambda raw: raw["cases"][0].update({"tags": ["multi_turn", "adversarial_ambiguous"]}),
            "canonical order",
        ),
    ],
)
def test_rejects_malformed_or_weakened_manifests(
    mutation: object,
    message: str,
) -> None:
    raw = _raw()
    mutation(raw)  # type: ignore[operator]

    with pytest.raises(CorpusManifestError, match=message):
        parse_manifest(raw)


def test_multi_turn_tags_require_real_complete_conversations() -> None:
    single = _raw()
    single["cases"][0]["conversation_id"] = "en-isolated"
    single["cases"][0]["turn_index"] = 1
    with pytest.raises(CorpusManifestError, match="cannot tag a single turn"):
        parse_manifest(single)

    gap = _raw()
    gap["cases"][1]["turn_index"] = 3
    with pytest.raises(CorpusManifestError, match="turn indexes MUST be consecutive"):
        parse_manifest(gap)

    partial = _raw()
    partial["cases"][0]["tags"].remove("multi_turn")
    with pytest.raises(CorpusManifestError, match="tag every multi-turn case"):
        parse_manifest(partial)


@pytest.mark.parametrize(
    ("tag", "remaining", "message"),
    [
        ("adversarial_ambiguous", 99, "adversarial_ambiguous"),
        ("sre_incident_rca", 149, "sre_incident_rca"),
        ("action_channel_attachment", 99, "action_channel_attachment"),
    ],
)
def test_required_tagged_subset_floors_cannot_be_weakened(
    tag: str,
    remaining: int,
    message: str,
) -> None:
    raw = _raw()
    retained = 0
    for case in raw["cases"]:
        if tag not in case["tags"]:
            continue
        retained += 1
        if retained > remaining:
            case["tags"].remove(tag)

    with pytest.raises(CorpusManifestError, match=message):
        parse_manifest(raw)


def test_multi_turn_conversation_floor_counts_groups_not_tagged_turns() -> None:
    raw = _raw()
    first_conversation = raw["cases"][0]["conversation_id"]
    for index, case in enumerate(raw["cases"][:2]):
        assert case["conversation_id"] == first_conversation
        case["conversation_id"] = f"en-reduced-{index}"
        case["turn_index"] = 1
        case["tags"].remove("multi_turn")

    with pytest.raises(CorpusManifestError, match="150 multi-turn conversations"):
        parse_manifest(raw)


def test_content_commitments_and_contract_binding_are_enforced() -> None:
    duplicate = _raw()
    duplicate["cases"][1]["content_commitment"] = duplicate["cases"][0]["content_commitment"]
    with pytest.raises(CorpusManifestError, match="content_commitment values MUST be unique"):
        parse_manifest(duplicate)

    mismatch = deepcopy(_raw())
    mismatch["qualification_contract_digest"] = "c" * 64
    with pytest.raises(CorpusManifestError, match="installed contract"):
        parse_manifest(mismatch)


def test_cli_reports_only_content_free_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_raw()), encoding="utf-8")

    assert main(["--manifest", str(path)]) == 0

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["turn_count"] == 500
    assert receipt["multi_turn_conversations"] == 150


def test_direct_script_entrypoint_is_runnable() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        (sys.executable, str(_SCRIPT), "--help"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    assert "--manifest" in completed.stdout
