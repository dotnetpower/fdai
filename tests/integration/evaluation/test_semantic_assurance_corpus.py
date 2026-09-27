"""Source-bound, content-free semantic assurance corpus checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from scripts.automation.build_semantic_assurance_corpus import (
    _partition,
    build_manifest,
    main,
)

_ROOT = Path(__file__).resolve().parents[3]
_ARTIFACT = _ROOT / "eval/golden-dataset/corpus-manifest.json"


def test_manifest_is_reproducible_and_accounts_for_every_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = build_manifest(_ROOT)
    assert manifest == json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    monkeypatch.setattr(sys, "argv", ["build_semantic_assurance_corpus.py", "--check"])
    assert main() == 0
    assert manifest["evidence_kind"] == "repository_source_only"
    assert manifest["operational_validation"] is False
    partitions = {part["kind"]: part for part in manifest["partitions"]}
    assert set(partitions) == {"golden", "declarations", "semantic_judgment", "incident_intent"}
    assert manifest["total_case_count"] == sum(part["case_count"] for part in partitions.values())
    assert manifest["total_exclusion_count"] == sum(
        part.get("exclusion_count", 0) for part in partitions.values()
    )
    golden = partitions["golden"]
    assert golden["case_count"] == sum(golden["locales"].values())
    assert golden["case_count"] == sum(golden["wording_styles"].values())
    assert golden["case_count"] == sum(golden["evidence_postures"].values())
    declarations = partitions["declarations"]
    assert declarations["case_count"] == sum(declarations["locales"].values())
    assert declarations["case_count"] == sum(declarations["evidence_postures"].values())
    assert set(declarations["evidence_postures"]) == set(declarations["grammar_digests"])
    assert declarations["readable_declaration_count"] > 0
    assert set(manifest["source_digests"]) == {
        "eval/golden-dataset/" + name
        for name in (
            "coverage.json",
            "expectations.json",
            "questions.source.yaml",
            "questions.en.json",
            "questions.ko.json",
            "semantic-judgment-assurance.json",
            "azure-incident-intent-golden.yaml",
        )
    }


def test_overlay_change_adds_case_and_changes_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes
    original_text = Path.read_text
    target = _ROOT / "eval/golden-dataset/semantic-judgment-assurance.json"
    baseline = build_manifest(_ROOT)
    payload = json.loads(original(target))
    payload["cases"].append({"id": "synthetic-extra-en", "locale": "en"})
    changed = json.dumps(payload).encode("utf-8")

    def read_bytes(path: Path) -> bytes:
        return changed if path == target else original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: (
            changed.decode("utf-8") if path == target else original_text(path, **kwargs)
        ),
    )
    derived = build_manifest(_ROOT)
    assert derived["total_case_count"] == baseline["total_case_count"] + 1
    assert derived["manifest_digest"] != baseline["manifest_digest"]
    assert (
        derived["source_digests"][target.relative_to(_ROOT).as_posix()]
        != (baseline["source_digests"][target.relative_to(_ROOT).as_posix()])
    )


def test_check_rejects_stale_artifact_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = Path.read_text
    monkeypatch.setattr(sys, "argv", ["build_semantic_assurance_corpus.py", "--check"])
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, **kwargs: "{}" if path == _ARTIFACT else original(path, **kwargs),
    )
    assert main() == 1
    assert "stale manifest" in capsys.readouterr().err


def test_duplicate_cases_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate case identities"):
        _partition("overlay", ["overlay:one", "overlay:one"])
