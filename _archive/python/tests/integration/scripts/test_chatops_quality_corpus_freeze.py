"""Tests for freezing a restricted ChatOps corpus without exposing its payload."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.evaluation.chatops_quality_corpus import CorpusManifestError
from scripts.evaluation.chatops_quality_corpus_freeze import (
    freeze_restricted_artifact,
    main,
    write_public_manifest,
)
from scripts.evaluation.chatops_quality_corpus_manifest import load_manifest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "evaluation"
    / "chatops_quality_corpus_freeze.py"
)
_SECRET_MARKER = "restricted-prompt-marker"


def _restricted() -> dict[str, Any]:
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
                cases.append(
                    _case(
                        locale=locale,
                        local_index=local_index,
                        conversation_id=f"{locale}-conversation-{conversation_index:03d}",
                        turn_index=turn_index,
                        tags=tags,
                    )
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
            cases.append(
                _case(
                    locale=locale,
                    local_index=local_index,
                    conversation_id=f"{locale}-single-{single_index:03d}",
                    turn_index=1,
                    tags=tags,
                )
            )
            local_index += 1
    return {
        "schema_version": 1,
        "corpus_id": "chatops-hidden",
        "corpus_version": "v1",
        "frozen_at": "2026-08-28T00:00:00Z",
        "freeze_revision": "a" * 40,
        "restricted_artifact_id": "hidden-artifact-v1",
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


def _case(
    *,
    locale: str,
    local_index: int,
    conversation_id: str,
    turn_index: int,
    tags: list[str],
) -> dict[str, object]:
    case_id = f"{locale}-case-{local_index:03d}"
    return {
        "case_id": case_id,
        "conversation_id": conversation_id,
        "turn_index": turn_index,
        "locale": locale,
        "content": f"{_SECRET_MARKER}:{case_id}",
        "label": {
            "expected_decision": "pass",
            "review_bucket": f"bucket-{local_index % 10}",
        },
        "tags": tags,
        "rubric_item_ids": list(range(1, 51)),
    }


def _write_restricted(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_freeze_creates_content_free_manifest_and_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    restricted = tmp_path / "restricted.json"
    public = tmp_path / "public.json"
    _write_restricted(restricted, _restricted())

    assert main(["--restricted-artifact", str(restricted), "--output", str(public)]) == 0

    manifest = load_manifest(public)
    output = public.read_text(encoding="utf-8")
    receipt = json.loads(capsys.readouterr().out)
    assert len(manifest.cases) == 500
    assert receipt["locales"] == {"en": 250, "ko": 250}
    assert receipt["public_manifest_created"] is True
    assert _SECRET_MARKER not in output
    assert "expected_decision" not in output

    assert main(["--restricted-artifact", str(restricted), "--output", str(public)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["public_manifest_created"] is False


def test_same_version_cannot_overwrite_frozen_commitments(tmp_path: Path) -> None:
    restricted = tmp_path / "restricted.json"
    public = tmp_path / "public.json"
    raw = _restricted()
    _write_restricted(restricted, raw)
    manifest = freeze_restricted_artifact(restricted)
    assert write_public_manifest(manifest, public) is True
    original = public.read_bytes()

    raw["cases"][0]["label"]["expected_decision"] = "fail"
    _write_restricted(restricted, raw)
    changed = freeze_restricted_artifact(restricted)

    with pytest.raises(CorpusManifestError, match="different frozen manifest"):
        write_public_manifest(changed, public)
    assert public.read_bytes() == original


def test_restricted_artifact_requires_owner_only_permissions(tmp_path: Path) -> None:
    restricted = tmp_path / "restricted.json"
    restricted.write_text(json.dumps(_restricted()), encoding="utf-8")
    restricted.chmod(0o644)

    with pytest.raises(CorpusManifestError, match="owner-only"):
        freeze_restricted_artifact(restricted)


def test_restricted_artifact_rejects_symbolic_links(tmp_path: Path) -> None:
    restricted = tmp_path / "restricted.json"
    linked = tmp_path / "linked.json"
    _write_restricted(restricted, _restricted())
    linked.symlink_to(restricted)

    with pytest.raises(CorpusManifestError, match="unavailable"):
        freeze_restricted_artifact(linked)


def test_failure_does_not_print_restricted_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    restricted = tmp_path / "restricted.json"
    public = tmp_path / "public.json"
    raw = _restricted()
    raw["cases"][0][_SECRET_MARKER] = True
    _write_restricted(restricted, raw)

    assert main(["--restricted-artifact", str(restricted), "--output", str(public)]) == 1

    captured = capsys.readouterr()
    assert _SECRET_MARKER not in captured.out
    assert _SECRET_MARKER not in captured.err
    assert not public.exists()


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
    assert "--restricted-artifact" in completed.stdout
