"""Offline CLI boundary and preservation tests; all receipts are explicitly synthetic."""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest
from fdai_service_contracts.cloud_knowledge import canonical_bytes
from fdai_service_contracts.cloud_knowledge_evaluation import (
    CASE_FLOORS,
    LANGUAGES,
    CloudKnowledgeEvaluationBatch,
    CloudKnowledgeEvaluationCase,
    CloudKnowledgeEvaluationError,
    CloudKnowledgeEvaluationObservation,
    CloudKnowledgeEvaluationPlan,
    CloudKnowledgeEvaluationReport,
    CloudKnowledgeQuestionSet,
    evaluate_cloud_knowledge_evidence,
)
from scripts.evaluation import cloud_knowledge_evidence as cli


@pytest.fixture(scope="module")
def encoded() -> bytes:
    cases = tuple(
        CloudKnowledgeEvaluationCase(
            case_id=f"{kind}-{index}",
            language=language,
            question=(
                f"What supports {kind} case {index}?"
                if language == "en"
                else f"{kind} 사례 {index}의 근거는 무엇인가요?"
            ),
            split="held_out" if index < held_out else "development",
            kind=kind,
            required_evidence_ids=(
                ()
                if kind == "negative"
                else (f"evidence:{kind}:{index}",)
                if kind == "single"
                else (f"evidence:{kind}:{index}", f"context:{kind}:{index}")
            ),
            forbidden_evidence_ids=(f"forbidden:{kind}:{index}",),
        )
        for kind, total, held_out in CASE_FLOORS
        for index in range(total)
        for language in LANGUAGES
    )
    questions = CloudKnowledgeQuestionSet(cases=cases)
    plan = CloudKnowledgeEvaluationPlan(
        corpus_digest="a" * 64,
        question_set_digest=questions.digest,
        recipe_digest="b" * 64,
        source_revision="c" * 40,
        evidence_venue="synthetic",
        question_set=questions,
    )
    plan_digest = plan.digest
    observations = tuple(
        CloudKnowledgeEvaluationObservation(
            plan_digest=plan_digest,
            case_id=case.case_id,
            language=case.language,
            returned_evidence_ids=case.required_evidence_ids,
            outcome="hold" if case.kind == "negative" else "answer",
            claim_count=int(case.kind != "negative"),
            cited_claim_count=int(case.kind != "negative"),
            material_claim_count=int(case.kind != "negative"),
            supported_material_claim_count=int(case.kind != "negative"),
            critical_claim_count=int(case.kind != "negative"),
            supported_critical_claim_count=int(case.kind != "negative"),
            citation_count=int(case.kind != "negative"),
            latency_ms=100.0,
            cost_usd=0.0,
            unapproved_effect=False,
        )
        for case in questions.cases
    )
    return canonical_bytes(CloudKnowledgeEvaluationBatch(plan=plan, observations=observations))


def _paths(tmp_path: Path, content: bytes) -> tuple[Path, Path]:
    source = tmp_path / "input.json"
    source.write_bytes(content)
    return source, tmp_path / "report.json"


def test_cli_uses_library_reduction_and_canonical_exclusive_private_output(
    tmp_path: Path, encoded: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    source, output = _paths(tmp_path, encoded)
    expected = evaluate_cloud_knowledge_evidence(cli.decode_evidence(encoded))

    assert cli.main([str(source), "--output", str(output)]) == 0

    assert output.read_bytes() == canonical_bytes(expected)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert source.read_bytes() == encoded
    assert capsys.readouterr().out == ""
    parsed = json.loads(output.read_bytes())
    assert parsed["numeric_status"] == "pass"
    assert parsed["production_qualified"] is False
    assert parsed["evidence_authenticity"] == "unverified"
    assert parsed["independent_human_review"] == "unverified"


def test_stdout_has_one_canonical_json_line_without_question_text(
    tmp_path: Path, encoded: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    source, output = _paths(tmp_path, encoded)
    expected = cli.evaluate_file(source)
    assert cli.main([str(source)]) == 0
    captured = capsys.readouterr()
    assert captured.out == canonical_bytes(expected).decode("utf-8") + "\n"
    assert captured.err == ""
    assert "What supports" not in captured.out
    assert "근거" not in captured.out
    assert not output.exists()


def test_empty_observation_set_reports_no_evidence_and_nonzero_exit(
    tmp_path: Path, encoded: bytes
) -> None:
    batch = cli.decode_evidence(encoded)
    content = canonical_bytes(CloudKnowledgeEvaluationBatch(plan=batch.plan, observations=()))
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 1
    report = json.loads(output.read_bytes())
    assert report["numeric_status"] == "no_evidence"
    assert report["observation_count"] == 0
    assert report["missing_observation_count"] == 160
    assert report["performance"]["cost_total_usd"] is None


def test_missing_korean_remains_a_counted_hold_at_the_cli(tmp_path: Path, encoded: bytes) -> None:
    batch = cli.decode_evidence(encoded)
    observations = tuple(item for item in batch.observations if item.language != "ko")
    content = canonical_bytes(
        CloudKnowledgeEvaluationBatch(plan=batch.plan, observations=observations)
    )
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 1
    report = json.loads(output.read_bytes())
    assert report["missing_observation_count"] == 80
    assert report["numeric_status"] == "hold"
    assert report["languages"][1]["complete_evidence_at_8"]["status"] == "no_evidence"
    assert report["languages"][1]["complete_evidence_at_8"]["denominator"] == 30


def test_known_failure_is_published_as_failure_not_silently_dropped(
    tmp_path: Path, encoded: bytes
) -> None:
    batch = cli.decode_evidence(encoded)
    first = batch.observations[0].model_copy(update={"unapproved_effect": True})
    changed = CloudKnowledgeEvaluationBatch(
        plan=batch.plan, observations=(first, *batch.observations[1:])
    )
    source, output = _paths(tmp_path, canonical_bytes(changed))
    assert cli.main([str(source), "--output", str(output)]) == 1
    report = json.loads(output.read_bytes())
    assert report["numeric_status"] == "fail"
    assert report["unapproved_effects"]["numerator"] == 159
    assert report["unapproved_effects"]["denominator"] == 160
    assert report["unapproved_effect_count"] == 1
    assert report["production_qualified"] is False


def test_operational_venue_cannot_upgrade_fabricated_numeric_receipts(
    tmp_path: Path, encoded: bytes
) -> None:
    batch = cli.decode_evidence(encoded)
    plan = CloudKnowledgeEvaluationPlan.model_validate(
        batch.plan.model_dump() | {"evidence_venue": "operational"}
    )
    plan_digest = plan.digest
    observations = tuple(
        item.model_copy(update={"plan_digest": plan_digest}) for item in batch.observations
    )
    content = canonical_bytes(CloudKnowledgeEvaluationBatch(plan=plan, observations=observations))
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 0
    report = json.loads(output.read_bytes())
    assert report["declared_evidence_venue"] == "operational"
    assert report["numeric_status"] == "pass"
    assert report["evidence_authenticity"] == "unverified"
    assert report["independent_human_review"] == "unverified"
    assert report["operational_authorization"] == "unverified"
    assert report["production_qualified"] is False


@pytest.mark.parametrize(
    "field",
    [b"production_qualified", b"operational_authorized", b"corpus_reviewed", b"denominator"],
)
def test_injected_authority_and_denominator_keys_fail_without_output(
    tmp_path: Path, encoded: bytes, field: bytes
) -> None:
    content = encoded.replace(b'"plan":{', b'"plan":{"' + field + b'":true,', 1)
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "invalid",
    [
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b"1e999",
        b"1e-999",
        b"true",
        b'"100"',
        b"-1",
        b"9" * 401,
    ],
)
def test_invalid_numeric_inputs_never_create_or_overwrite_output(
    tmp_path: Path,
    encoded: bytes,
    existing: bool,
    invalid: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = encoded.replace(b'"latency_ms":100.0', b'"latency_ms":' + invalid, 1)
    assert content != encoded
    source, output = _paths(tmp_path, content)
    if existing:
        output.write_bytes(b"retained report")
        output.chmod(0o640)
    assert cli.main([str(source), "--output", str(output)]) == 2
    if existing:
        assert output.read_bytes() == b"retained report"
        assert stat.S_IMODE(output.stat().st_mode) == 0o640
    else:
        assert not output.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cloud knowledge evaluation failed:" in captured.err


@pytest.mark.parametrize("value", [b"true", b"false", b"1.0", b'"1"', b"-1", b"9" * 401])
def test_json_counts_reject_booleans_fractional_values_and_overflow(
    encoded: bytes, value: bytes
) -> None:
    content = encoded.replace(b'"claim_count":1', b'"claim_count":' + value, 1)
    assert content != encoded
    with pytest.raises(CloudKnowledgeEvaluationError):
        cli.decode_evidence(content)


@pytest.mark.parametrize(
    ("token", "expected"),
    [(b"5e-324", 5e-324), (b"0e999999999999999999999999", 0.0), (b"-0.0", 0.0)],
)
def test_representable_subnormal_and_zero_exponents_do_not_raise_overflow(
    encoded: bytes, token: bytes, expected: float
) -> None:
    content = encoded.replace(b'"cost_usd":0.0', b'"cost_usd":' + token, 1)
    batch = cli.decode_evidence(content)
    assert batch.observations[0].cost_usd == expected
    assert b'"cost_usd":-0.0' not in canonical_bytes(batch)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'"plan":{', b'"plan":{},"plan":{'),
        (b'"corpus_digest":', b'"corpus_digest":null,"corpus_digest":'),
        (b'"claim_count":1', b'"claim_count":0,"claim_count":1'),
        (b'"claim_count":1', b'"claim_count":0,"claim_\\u0063ount":1'),
    ],
)
def test_duplicate_keys_at_all_depths_are_rejected_before_schema_coercion(
    encoded: bytes, old: bytes, new: bytes
) -> None:
    with pytest.raises(CloudKnowledgeEvaluationError, match="duplicate keys"):
        cli.decode_evidence(encoded.replace(old, new, 1))


@pytest.mark.parametrize(
    "content",
    [b"", b"[]", b"null", b"true", b"{}", b"\xff", b"\xef\xbb\xbf{}", b'{"plan":', b"{}{}"],
)
def test_invalid_utf8_json_and_roots_fail_without_leaking_details(
    tmp_path: Path, content: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(source) not in captured.err
    assert not output.exists()


def test_bounded_error_never_echoes_question_or_path(
    tmp_path: Path, encoded: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    content = encoded.replace(b'"latency_ms":100.0', b'"latency_ms":"private-question-marker"', 1)
    source, output = _paths(tmp_path, content)
    assert cli.main([str(source), "--output", str(output)]) == 2
    error = capsys.readouterr().err
    assert "private-question-marker" not in error
    assert str(source) not in error
    assert "input_value" not in error


def test_json_depth_tokens_and_bytes_are_bounded_before_reduction(
    encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep = b"[" * (cli.MAX_JSON_DEPTH + 1) + b"0" + b"]" * (cli.MAX_JSON_DEPTH + 1)
    with pytest.raises(CloudKnowledgeEvaluationError, match="nesting bound"):
        cli.decode_evidence(deep)
    monkeypatch.setattr(cli, "MAX_JSON_TOKENS", 3)
    with pytest.raises(CloudKnowledgeEvaluationError, match="structural bound"):
        cli.decode_evidence(b"[0,0,0,0,0]")
    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", len(encoded) - 1)
    with pytest.raises(CloudKnowledgeEvaluationError, match="byte bound"):
        cli.decode_evidence(encoded)


def test_quoted_braces_and_escaped_quotes_do_not_consume_nesting_budget() -> None:
    cli._json_budget(json.dumps({"question": '"' + "[" * 100 + "}" * 100}))


def test_existing_regular_output_is_never_truncated_replaced_or_chmodded(
    tmp_path: Path, encoded: bytes
) -> None:
    source, output = _paths(tmp_path, encoded)
    output.write_bytes(b"preserve original")
    output.chmod(0o640)
    before = output.stat()
    assert cli.main([str(source), "--output", str(output)]) == 2
    after = output.stat()
    assert output.read_bytes() == b"preserve original"
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
        before.st_ino,
        before.st_mtime_ns,
        before.st_mode,
    )


def test_output_equal_to_input_preserves_input_bytes(tmp_path: Path, encoded: bytes) -> None:
    source, _ = _paths(tmp_path, encoded)
    assert cli.main([str(source), "--output", str(source)]) == 2
    assert source.read_bytes() == encoded


@pytest.mark.parametrize("dangling", [False, True])
def test_output_links_are_not_followed_or_replaced(
    tmp_path: Path, encoded: bytes, dangling: bool
) -> None:
    source, output = _paths(tmp_path, encoded)
    target = tmp_path / "target.json"
    if not dangling:
        target.write_bytes(b"retained target")
    output.symlink_to(target)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert output.is_symlink()
    if dangling:
        assert not target.exists()
    else:
        assert target.read_bytes() == b"retained target"


def test_output_hardlink_and_directory_are_preserved(tmp_path: Path, encoded: bytes) -> None:
    source, output = _paths(tmp_path, encoded)
    target = tmp_path / "target.json"
    target.write_bytes(b"original")
    os.link(target, output)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert target.read_bytes() == output.read_bytes() == b"original"
    directory = tmp_path / "existing-directory"
    directory.mkdir()
    assert cli.main([str(source), "--output", str(directory)]) == 2
    assert directory.is_dir()


def test_intermediate_directory_links_are_rejected_for_input_and_output(
    tmp_path: Path, encoded: bytes
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    source, output = _paths(real, encoded)
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    assert cli.main([str(link / source.name), "--output", str(output)]) == 2
    assert cli.main([str(source), "--output", str(link / output.name)]) == 2
    assert not output.exists()


def test_input_links_directory_fifo_and_missing_file_fail_without_hanging(
    tmp_path: Path, encoded: bytes
) -> None:
    source, output = _paths(tmp_path, encoded)
    symbolic = tmp_path / "symbolic-input"
    symbolic.symlink_to(source)
    hard = tmp_path / "hard-input"
    os.link(source, hard)
    fifo = tmp_path / "fifo-input"
    os.mkfifo(fifo, 0o600)
    for path in (symbolic, hard, tmp_path, fifo, tmp_path / "missing"):
        assert cli.main([str(path), "--output", str(output)]) == 2
        assert not output.exists()
    assert source.read_bytes() == encoded


def test_read_byte_limit_is_enforced_before_json_decode(
    tmp_path: Path, encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path, encoded)
    monkeypatch.setattr(cli, "MAX_INPUT_BYTES", len(encoded) - 1)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert not output.exists()


def test_input_change_during_read_fails_before_publication(
    tmp_path: Path, encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path, encoded)
    original_stat = cli.os.fstat
    changed = False

    def change_after_stat(descriptor: int) -> os.stat_result:
        nonlocal changed
        before = original_stat(descriptor)
        if not changed:
            changed = True
            source.write_bytes(encoded + b" ")
        return before

    monkeypatch.setattr(cli.os, "fstat", change_after_stat)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert changed
    assert not output.exists()


def test_relative_paths_work_but_parent_traversal_does_not(
    tmp_path: Path, encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path, encoded)
    monkeypatch.chdir(tmp_path)
    assert cli.main([source.name, "--output", output.name]) == 0
    subdirectory = tmp_path / "child"
    subdirectory.mkdir()
    assert cli.main(["child/../input.json", "--output", "unused.json"]) == 2
    assert not (tmp_path / "unused.json").exists()


def test_cli_uses_exclusive_open_even_when_output_appears_after_evaluation(
    tmp_path: Path, encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path, encoded)
    original = cli.evaluate_file

    def create_competitor(path: Path) -> CloudKnowledgeEvaluationReport:
        report = original(path)
        output.write_bytes(b"concurrent original")
        return report

    monkeypatch.setattr(cli, "evaluate_file", create_competitor)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert output.read_bytes() == b"concurrent original"


def test_output_fsync_failure_is_not_reported_as_success(
    tmp_path: Path,
    encoded: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, output = _paths(tmp_path, encoded)

    def fail_sync(descriptor: int) -> NoReturn:
        raise OSError("private-storage-error")

    monkeypatch.setattr(cli.os, "fsync", fail_sync)
    assert cli.main([str(source), "--output", str(output)]) == 2
    assert output.exists()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-storage-error" not in captured.err
    assert cli.main([str(source), "--output", str(output)]) == 2


def test_reduction_and_cli_never_call_network_or_subprocesses(
    tmp_path: Path, encoded: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path, encoded)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("offline evidence attempted external I/O")

    for attribute in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, attribute, forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(sys, "argv", ["cloud-evidence", str(source), "--output", str(output)])
    assert cli.main() == 0
    assert cli.summarize_evidence(json.loads(encoded))["production_qualified"] is False
