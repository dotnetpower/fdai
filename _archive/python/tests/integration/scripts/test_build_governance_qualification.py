"""F06.2 governance qualification record CLI."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).parents[3]
_SCRIPT = _ROOT / "scripts/governance/build-governance-qualification.py"
_CUTOFF = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_governance_qualification", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cases(truth_flagged: bool = True) -> list[dict[str, str]]:
    cases = [
        {"case_id": f"v{i}", "group_id": f"g{i}", "truth": "violation", "verdict": "flagged"}
        for i in range(4)
    ]
    cases += [
        {"case_id": f"c{i}", "group_id": f"h{i}", "truth": "compliant", "verdict": "not_flagged"}
        for i in range(4)
    ]
    return cases


def _document(*, state: str = "available", digest: str | None = None) -> dict[str, object]:
    from fdai.core.governance_qualification import (  # local import keeps module import cheap
        CohortCase,
        GroundTruth,
        Verdict,
        freeze_cohort,
    )

    frozen = freeze_cohort(
        CohortCase(c["case_id"], c["group_id"], GroundTruth(c["truth"]), Verdict(c["verdict"]))
        for c in _cases()
    )
    return {
        "binding": {
            "installation_id": "inst-1",
            "management_scope_id": "scope-1",
            "environment_class": "development",
            "rule_generation_digest": "sha256:" + "b" * 64,
            "ontology_release_digest": "sha256:" + "c" * 64,
            "provider_revisions": {"drift": "r1"},
            "evidence_cutoff": _CUTOFF.isoformat(),
        },
        "required_source_ids": ["drift"],
        "max_age_seconds": int(timedelta(hours=1).total_seconds()),
        "observations": [
            {
                "source_id": "drift",
                "scope_id": "scope-1",
                "identity_ref": "identity-1",
                "state": state,
                "observed_at": (_CUTOFF - timedelta(minutes=5)).isoformat(),
                "evidence_digest": "sha256:" + "a" * 64,
            }
        ],
        "cohort": {"cases": _cases(), "digest": digest or frozen.digest},
    }


def _run(cli: ModuleType, tmp_path: Path, document: object, capsys) -> tuple[int, str, str]:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    code = cli.main([str(path)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_complete_input_is_ready_for_review_with_no_authority(cli, tmp_path, capsys) -> None:
    code, out, _ = _run(cli, tmp_path, _document(), capsys)

    record = json.loads(out)
    assert code == 0
    assert record["readiness"] == "ready_for_review"
    assert record["authority"] == "none"
    assert record["measurement"]["false_positive_rate"]["denominator"] == 4


def test_a_held_source_blocks_with_exit_two_and_names_the_hold(cli, tmp_path, capsys) -> None:
    code, out, _ = _run(cli, tmp_path, _document(state="revoked"), capsys)

    record = json.loads(out)
    assert code == 2
    assert record["readiness"] == "blocked"
    assert record["holds"] == [["drift", "revoked"]]


def test_a_changed_cohort_digest_is_invalid_input(cli, tmp_path, capsys) -> None:
    code, out, err = _run(cli, tmp_path, _document(digest="sha256:" + "0" * 64), capsys)

    assert code == 1
    assert out == ""
    assert "invalid input" in err


@pytest.mark.parametrize("document", [[], {"binding": {}}])
def test_malformed_input_never_prints_a_record(cli, tmp_path, capsys, document) -> None:
    code, out, _ = _run(cli, tmp_path, document, capsys)

    assert code == 1
    assert out == ""
