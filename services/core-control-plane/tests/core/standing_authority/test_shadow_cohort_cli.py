"""Tests for the strictly local-only A3-E shadow cohort CLI and corpus decoder.

Covers:
- A complete local corpus runs end to end and writes exactly one receipt.
- Non-local venue or evidence class is refused before anything runs.
- Closed schema: unknown and missing keys fail closed.
- Bounded input: document bytes, case count, review count, per-case and total elapsed.
- Output containment: required directory, symlinked directory or parent rejected,
  symlinked corpus rejected, receipt resolves inside the declared directory.
- Exit codes for usage failure, incomplete cohort, and deadline overrun.
- Static proofs: neither module imports network, Azure, provider, database, delivery,
  executor, runtime, or ``ActionPromotionRegistry`` paths.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.standing_authority.shadow_cohort_cli import (
    CLI_DEADLINE_S,
    EXIT_DEADLINE,
    EXIT_INCOMPLETE,
    EXIT_OK,
    EXIT_USAGE,
    main,
)
from fdai.core.standing_authority.shadow_cohort_corpus import (
    CORPUS_SCHEMA_VERSION,
    MAX_CASES,
    MAX_CORPUS_BYTES,
    CohortCorpusError,
    decode_corpus_document,
)
from tests.core.standing_authority.inertness_scan import find_inertness_violations

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
CLI_PATH = SOURCE_ROOT / "core" / "standing_authority" / "shadow_cohort_cli.py"
CORPUS_PATH = SOURCE_ROOT / "core" / "standing_authority" / "shadow_cohort_corpus.py"

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
REVISION_ID = "sha256:" + "a" * 64
AUTH_DIGEST = "sha256:" + "f" * 64
EVIDENCE_1 = "sha256:" + "e1" + "0" * 62
EVIDENCE_2 = "sha256:" + "e2" + "0" * 62
CREATOR = "human:creator"
REVIEWER_A = "human:reviewer-a"
REVIEWER_B = "human:reviewer-b"


def _instant(offset_minutes: int = 0) -> str:
    return (NOW + timedelta(minutes=offset_minutes)).isoformat().replace("+00:00", "Z")


def _candidate(family: str = "family:one") -> dict[str, Any]:
    return {
        "family_id": family,
        "revision_id": REVISION_ID,
        "fence": {
            "family_id": family,
            "revision_id": REVISION_ID,
            "fencing_generation": 1,
            "transition_digest": "sha256:" + "d" * 64,
        },
        "eligible_action_types": ["ops.scale-out"],
        "ineligible_provider_action_types": [],
        "evidence_requirements": [EVIDENCE_1, EVIDENCE_2],
        "source_revision_id": "source:v1",
        "creator_principal": CREATOR,
        "authentication_evidence_digest": AUTH_DIGEST,
        "created_at": _instant(),
        "required_reviewer_principals": [REVIEWER_A, REVIEWER_B],
        "quorum_required": 2,
    }


def _review(reviewer: str, minutes: int) -> dict[str, Any]:
    return {
        "reviewer_principal": reviewer,
        "decision": "approve",
        "reviewed_at": _instant(minutes),
        "authentication_evidence_digest": AUTH_DIGEST,
        "evidence_digests": [EVIDENCE_1, EVIDENCE_2],
    }


def _eligible_case(case_id: str = "eligible-1") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "expected_disposition": "eligible",
        "expected_denial_reason": None,
        "elapsed_s": 0.25,
        "candidate": _candidate(),
        "reviews": [_review(REVIEWER_A, 1), _review(REVIEWER_B, 2)],
        "external_denial": None,
    }


def _denied_case(case_id: str = "revoked-1") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "expected_disposition": "denied",
        "expected_denial_reason": "revocation_request",
        "elapsed_s": 0.1,
        "candidate": _candidate("family:two"),
        "reviews": [],
        "external_denial": {
            "reason": "revocation_request",
            "detail": "owner revoked the authorization",
            "actor_ref": "human:owner",
            "authentication_evidence_digest": AUTH_DIGEST,
            "occurred_at": _instant(3),
        },
    }


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "venue": "local",
        "evidence_class": "synthetic_development",
        "source_revision_id": "source:v1",
        "cases": [_eligible_case(), _denied_case()],
    }
    document.update(overrides)
    return document


def _write(tmp_path: Path, document: object, name: str = "corpus.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests: decoder happy path and local-only enforcement
# ---------------------------------------------------------------------------


def test_decoder_builds_manifest_corpus_and_elapsed_map() -> None:
    decoded = decode_corpus_document(json.dumps(_document()))
    assert decoded.venue == "local"
    assert decoded.evidence_class == "synthetic_development"
    assert len(decoded.corpus) == 2
    assert {entry.case_id for entry in decoded.manifest.entries} == {"eligible-1", "revoked-1"}
    assert decoded.per_case_elapsed_s == {"eligible-1": 0.25, "revoked-1": 0.1}


@pytest.mark.parametrize("venue", ["runtime", "dev", "prod", "governed"])
def test_non_local_venue_is_refused(venue: str) -> None:
    with pytest.raises(CohortCorpusError, match="venue MUST be 'local'"):
        decode_corpus_document(json.dumps(_document(venue=venue)))


@pytest.mark.parametrize("evidence_class", ["runtime_governed", "live", "production"])
def test_non_synthetic_evidence_class_is_refused(evidence_class: str) -> None:
    with pytest.raises(CohortCorpusError, match="evidence_class MUST be"):
        decode_corpus_document(json.dumps(_document(evidence_class=evidence_class)))


def test_wrong_schema_version_is_refused() -> None:
    with pytest.raises(CohortCorpusError, match="schema_version"):
        decode_corpus_document(json.dumps(_document(schema_version="a3e-local-cohort-v2")))


# ---------------------------------------------------------------------------
# Tests: closed schema and bounded input
# ---------------------------------------------------------------------------


def test_unknown_document_key_is_refused() -> None:
    document = _document()
    document["live_endpoint"] = "https://example.invalid"
    with pytest.raises(CohortCorpusError, match="unknown key"):
        decode_corpus_document(json.dumps(document))


def test_unknown_case_key_is_refused() -> None:
    document = _document()
    document["cases"][0]["subscription_id"] = "abc"
    with pytest.raises(CohortCorpusError, match="unknown key"):
        decode_corpus_document(json.dumps(document))


def test_missing_case_key_is_refused() -> None:
    document = _document()
    del document["cases"][0]["reviews"]
    with pytest.raises(CohortCorpusError, match="missing required key"):
        decode_corpus_document(json.dumps(document))


def test_oversized_document_is_refused() -> None:
    padded = "x" * (MAX_CORPUS_BYTES + 1)
    with pytest.raises(CohortCorpusError, match="exceeds"):
        decode_corpus_document(padded)


def test_too_many_cases_are_refused() -> None:
    document = _document(cases=[_eligible_case(f"case-{index}") for index in range(MAX_CASES + 1)])
    with pytest.raises(CohortCorpusError, match=f"more than {MAX_CASES} cases"):
        decode_corpus_document(json.dumps(document))


def test_too_many_reviews_are_refused() -> None:
    case = _eligible_case()
    case["reviews"] = [_review(REVIEWER_A, index) for index in range(17)]
    with pytest.raises(CohortCorpusError, match="more than"):
        decode_corpus_document(json.dumps(_document(cases=[case])))


def test_per_case_elapsed_bound_is_enforced() -> None:
    case = _eligible_case()
    case["elapsed_s"] = 31.0
    with pytest.raises(CohortCorpusError, match="per-case bound"):
        decode_corpus_document(json.dumps(_document(cases=[case])))


def test_total_elapsed_bound_is_enforced() -> None:
    cases = []
    for index in range(100):
        case = _eligible_case(f"case-{index}")
        case["elapsed_s"] = 30.0
        cases.append(case)
    with pytest.raises(CohortCorpusError, match="total bound"):
        decode_corpus_document(json.dumps(_document(cases=cases)))


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_non_finite_elapsed_is_refused(value: float) -> None:
    case = _eligible_case()
    case["elapsed_s"] = value
    document = json.dumps(_document(cases=[case]))
    with pytest.raises(CohortCorpusError):
        decode_corpus_document(document)


def test_duplicate_case_id_is_refused() -> None:
    with pytest.raises(CohortCorpusError, match="duplicate case_id"):
        decode_corpus_document(json.dumps(_document(cases=[_eligible_case(), _eligible_case()])))


def test_naive_timestamp_is_refused() -> None:
    case = _eligible_case()
    case["candidate"]["created_at"] = "2026-09-13T12:00:00"
    with pytest.raises(CohortCorpusError, match="timezone-aware"):
        decode_corpus_document(json.dumps(_document(cases=[case])))


def test_malformed_json_is_refused() -> None:
    with pytest.raises(CohortCorpusError, match="not valid JSON"):
        decode_corpus_document("{not json")


def test_non_object_document_is_refused() -> None:
    with pytest.raises(CohortCorpusError, match="JSON object"):
        decode_corpus_document("[]")


def test_all_denied_corpus_is_refused_by_the_manifest() -> None:
    from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError

    with pytest.raises(AuthorizationLifecycleError, match="all-denied"):
        decode_corpus_document(json.dumps(_document(cases=[_denied_case()])))


# ---------------------------------------------------------------------------
# Tests: CLI behaviour
# ---------------------------------------------------------------------------


def test_cli_runs_and_writes_exactly_one_local_receipt(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    out = tmp_path / "artifacts"
    code = main(["--corpus", str(corpus), "--output-dir", str(out)])
    assert code == EXIT_OK
    receipts = sorted(out.glob("cohort-receipt-*.json"))
    assert len(receipts) == 1
    payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert payload["venue"] == "local"
    assert payload["evidence_class"] == "synthetic_development"
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["complete"] is True
    assert payload["zero_policy_escapes"] is True


def test_cli_reports_a_policy_escape_as_incomplete(tmp_path: Path) -> None:
    document = _document()
    # Declare a MISSING_EVIDENCE denial but supply complete evidence, so the
    # actual disposition cannot match the predeclared one.
    mismatched = _eligible_case("mismatch-1")
    mismatched["expected_disposition"] = "denied"
    mismatched["expected_denial_reason"] = "missing_evidence"
    document["cases"] = [_eligible_case(), mismatched]
    corpus = _write(tmp_path, document)
    out = tmp_path / "artifacts"
    code = main(["--corpus", str(corpus), "--output-dir", str(out)])
    assert code == EXIT_INCOMPLETE
    receipts = sorted(out.glob("cohort-receipt-*.json"))
    assert len(receipts) == 1
    payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert payload["zero_policy_escapes"] is False


def test_cli_refuses_non_local_corpus(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document(venue="runtime"))
    out = tmp_path / "artifacts"
    assert main(["--corpus", str(corpus), "--output-dir", str(out)]) == EXIT_USAGE
    assert not out.exists()


def test_cli_reports_usage_exit_for_an_all_denied_corpus(tmp_path: Path) -> None:
    """`build_manifest` raises the parent error type; it must still exit 2, not crash."""
    corpus = _write(tmp_path, _document(cases=[_denied_case()]))
    out = tmp_path / "artifacts"
    assert main(["--corpus", str(corpus), "--output-dir", str(out)]) == EXIT_USAGE
    assert not out.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision_id", "not-a-digest"),
        ("transition_digest", "nope"),
        ("fencing_generation", 0),
    ],
)
def test_cli_reports_usage_exit_for_nested_record_errors(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """`LifecycleFence` and the candidate builder raise the parent error type."""
    case = _eligible_case()
    case["candidate"]["fence"][field] = value
    corpus = _write(tmp_path, _document(cases=[case]))
    out = tmp_path / "artifacts"
    assert main(["--corpus", str(corpus), "--output-dir", str(out)]) == EXIT_USAGE
    assert not out.exists()


def test_cli_reports_usage_exit_for_a_non_human_creator(tmp_path: Path) -> None:
    case = _eligible_case()
    case["candidate"]["creator_principal"] = "agent:odin"
    corpus = _write(tmp_path, _document(cases=[case]))
    out = tmp_path / "artifacts"
    assert main(["--corpus", str(corpus), "--output-dir", str(out)]) == EXIT_USAGE
    assert not out.exists()


def test_cli_refuses_missing_corpus(tmp_path: Path) -> None:
    out = tmp_path / "artifacts"
    code = main(["--corpus", str(tmp_path / "absent.json"), "--output-dir", str(out)])
    assert code == EXIT_USAGE
    assert not out.exists()


def test_cli_refuses_symlinked_corpus(tmp_path: Path) -> None:
    real = _write(tmp_path, _document())
    link = tmp_path / "linked.json"
    link.symlink_to(real)
    out = tmp_path / "artifacts"
    assert main(["--corpus", str(link), "--output-dir", str(out)]) == EXIT_USAGE


def test_cli_refuses_symlinked_output_dir(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    real = tmp_path / "real-out"
    real.mkdir()
    link = tmp_path / "linked-out"
    link.symlink_to(real, target_is_directory=True)
    assert main(["--corpus", str(corpus), "--output-dir", str(link)]) == EXIT_USAGE
    assert not sorted(real.glob("cohort-receipt-*.json"))


def test_cli_refuses_symlinked_output_parent(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    target = linked_parent / "nested"
    assert main(["--corpus", str(corpus), "--output-dir", str(target)]) == EXIT_USAGE
    assert not (real_parent / "nested").exists()


def test_cli_refuses_output_dir_that_is_a_file(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    assert main(["--corpus", str(corpus), "--output-dir", str(occupied)]) == EXIT_USAGE


def test_cli_requires_output_dir(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    with pytest.raises(SystemExit):
        main(["--corpus", str(corpus)])


@pytest.mark.parametrize("deadline", [0.0, -1.0, CLI_DEADLINE_S + 1.0])
def test_cli_rejects_out_of_range_deadline(tmp_path: Path, deadline: float) -> None:
    corpus = _write(tmp_path, _document())
    out = tmp_path / "artifacts"
    code = main(["--corpus", str(corpus), "--output-dir", str(out), "--deadline-s", str(deadline)])
    assert code == EXIT_USAGE


def test_cli_reports_deadline_overrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = _write(tmp_path, _document())
    out = tmp_path / "artifacts"
    ticks = iter([0.0, 1000.0])
    monkeypatch.setattr(
        "fdai.core.standing_authority.shadow_cohort_cli.time.monotonic",
        lambda: next(ticks),
    )
    code = main(["--corpus", str(corpus), "--output-dir", str(out)])
    assert code == EXIT_DEADLINE
    assert not sorted(out.glob("cohort-receipt-*.json")) if out.exists() else True


def test_cli_receipt_resolves_inside_the_declared_directory(tmp_path: Path) -> None:
    corpus = _write(tmp_path, _document())
    out = tmp_path / "nested" / "artifacts"
    assert main(["--corpus", str(corpus), "--output-dir", str(out)]) == EXIT_OK
    receipts = sorted(out.glob("cohort-receipt-*.json"))
    assert len(receipts) == 1
    assert receipts[0].resolve().parent == out.resolve()


def test_cli_accepts_a_relative_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = _write(tmp_path, _document())
    monkeypatch.chdir(tmp_path)
    assert main(["--corpus", str(corpus), "--output-dir", "relative-out"]) == EXIT_OK
    assert len(sorted((tmp_path / "relative-out").glob("cohort-receipt-*.json"))) == 1


# ---------------------------------------------------------------------------
# Static proofs: no network, provider, registry, or runtime reach
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORT_PREFIXES = (
    "azure",
    "aiohttp",
    "httpx",
    "requests",
    "socket",
    "ssl",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncpg",
    "psycopg",
    "sqlalchemy",
    "boto3",
    "subprocess",
    "fdai.delivery",
    "fdai.runtime",
    "fdai.composition",
    "fdai.core.risk_gate",
    "fdai.core.executor",
    "fdai.core.control_loop",
    "fdai.shared.providers",
)


@pytest.mark.parametrize("module_path", [CLI_PATH, CORPUS_PATH])
def test_local_cohort_modules_reach_no_network_provider_or_registry(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    offenders = [
        module
        for module in modules
        if module.split(".")[0] in {"azure", "socket", "ssl", "http", "urllib", "subprocess"}
        or module.startswith(_FORBIDDEN_IMPORT_PREFIXES)
    ]
    assert offenders == [], f"{module_path.name} imports forbidden module(s): {offenders}"


@pytest.mark.parametrize("module_path", [CLI_PATH, CORPUS_PATH])
def test_local_cohort_modules_never_name_the_promotion_registry(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "ActionPromotionRegistry" not in identifiers
    assert "consider_promotion" not in identifiers


def test_no_shipped_module_reaches_the_local_cli_or_decoder() -> None:
    """Whole-tree scan; a hardcoded authority-root list would miss shipped surfaces."""
    violations = find_inertness_violations(
        SOURCE_ROOT,
        forbidden_modules=(
            "fdai.core.standing_authority.shadow_cohort_cli",
            "fdai.core.standing_authority.shadow_cohort_corpus",
        ),
        forbidden_symbols=frozenset({"shadow_cohort_cli", "shadow_cohort_corpus"}),
    )
    assert violations == [], f"shipped modules reach the local cohort CLI: {violations}"
