from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fdai.core.conversation_assurance import PrivateJsonlLedger
from scripts.automation.conversation_assurance_aks import AksBusinessServiceBinding
from scripts.automation.conversation_assurance_harness import ImprovementState
from scripts.automation.conversation_assurance_improvement_cli import (
    _arm_browser,
    _automatic_failure_class,
    _measure,
    _measurement_outcome,
    _parser,
    _prepare,
    _prepare_aks_series,
    _record_browser_failure,
    _record_browser_measurement,
    _run_aks_browser_series,
    _summary,
    _terminal_measurement_outcome,
)


def _private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    os.chmod(path, 0o600)


def _corpus(path: Path) -> None:
    _private_json(
        path,
        {
            "schema_version": "1.0.0",
            "cases": [
                {
                    "case_id": "fresh-read-case-en",
                    "suite": "external",
                    "locale": "en",
                    "question": "Which current resource states are supported by complete evidence?",
                    "expected_primary_agent": "Heimdall",
                    "expected_routing_method": "semantic_judgment",
                    "allowed_contributors": [],
                    "expected_handoff": False,
                    "expected_handoff_owner": None,
                    "t2_expectation": "forbidden",
                }
            ],
        },
    )


def _readiness(path: Path, *, corpus_digest: str | None = None) -> None:
    _private_json(
        path,
        {
            "capabilities": [
                {
                    "function_name": "query.resource_state_inventory",
                    "declared": True,
                    "bound": True,
                    "reachable": True,
                    "evidence_ready": True,
                    "provided_authority": "azure_resource_graph",
                    "unavailable_reason": None,
                }
            ],
            "assurance_corpus_digest": corpus_digest,
        },
    )


def test_prepare_binds_clean_revision_novel_question_and_readiness(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    readiness = tmp_path / "readiness.json"
    _corpus(corpus)
    _readiness(readiness)

    run = _prepare(
        project=tmp_path,
        corpus_path=corpus,
        readiness_path=readiness,
        run_id="improvement-one",
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure_resource_graph",
        source_revision="a" * 40,
        worktree_dirty=False,
    )

    assert run.state is ImprovementState.DRY_RUN_VALIDATED
    assert run.measurement_attempts == 0
    assert run.expected_authority == run.provided_authority


def test_prepare_aks_series_creates_three_private_runs_without_target_names_in_summary(
    tmp_path: Path,
) -> None:
    readiness = tmp_path / "readiness.json"
    runtime_env = tmp_path / "runtime.env"
    _readiness(readiness)
    runtime_env.write_text("FDAI_OTHER=value\n", encoding="utf-8")
    runtime_env.chmod(0o600)
    binding = AksBusinessServiceBinding(
        cluster_name="actual-cluster-private",
        provider_ref="/subscriptions/private/resourceGroups/private/providers/"
        "Microsoft.ContainerService/managedClusters/actual-cluster-private",
        resource_id="resource-private",
        business_service_name="actual-checkout-private",
    )

    runs = _prepare_aks_series(
        project=tmp_path,
        readiness_path=readiness,
        runtime_env_path=runtime_env,
        run_prefix="aks-series-one",
        source_revision="a" * 40,
        worktree_dirty=False,
        bindings=(binding,),
    )

    assert len(runs) == 3
    assert all(run.state is ImprovementState.DRY_RUN_VALIDATED for run in runs)
    rendered = json.dumps([_summary(run) for run in runs], sort_keys=True)
    assert "actual-cluster-private" not in rendered
    assert "actual-checkout-private" not in rendered
    corpus_root = tmp_path / ".fdai/conversation-assurance/aks-improvement-corpora/aks-series-one"
    case_paths = [corpus_root / f"aks-series-one-{index}.json" for index in range(1, 4)]
    questions = [
        json.loads(path.read_text(encoding="utf-8"))["cases"][0]["question"] for path in case_paths
    ]
    assert len(questions) == 3
    assert all("actual-cluster-private" in question for question in questions)
    assert all("actual-checkout-private" in question for question in questions)
    runtime_corpus = corpus_root / "aks-series-one-runtime.json"
    runtime_payload = json.loads(runtime_corpus.read_text(encoding="utf-8"))
    assert len(runtime_payload["cases"]) == 3
    runtime_environment = runtime_env.read_text(encoding="utf-8")
    corpus_binding = f"FDAI_CONVERSATION_ASSURANCE_CORPUS_FILE={runtime_corpus.resolve()}"
    assert corpus_binding in runtime_environment
    assert "FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST=" in runtime_environment


def test_measure_consumes_one_attempt_and_preserves_terminal_states(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    readiness = tmp_path / "readiness.json"
    _corpus(corpus)
    _readiness(readiness)
    prepared = _prepare(
        project=tmp_path,
        corpus_path=corpus,
        readiness_path=readiness,
        run_id="improvement-one",
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure_resource_graph",
        source_revision="a" * 40,
        worktree_dirty=False,
    )

    async def start(project: Path, _request: object) -> dict[str, object]:
        PrivateJsonlLedger(project / ".fdai/conversation-assurance/transcripts.jsonl").append(
            {
                "case_id": prepared.case_id,
                "terminal_state": "held",
                "answer_digest": "b" * 64,
                "answer_generation": {"state": "completed", "mode": "semantic"},
                "assessment_state": "deferred",
                "assessment_reasons": ["provider_http_429"],
                "score": None,
                "verdict": None,
            }
        )
        return {"state": "held", "reason": "assessment_deferred:provider_http_429"}

    measured = asyncio.run(
        _measure(
            project=tmp_path,
            corpus_path=corpus,
            run_id=prepared.run_id,
            source_revision=prepared.source_revision,
            worktree_dirty=False,
            start=start,
        )
    )

    assert measured.state is ImprovementState.HELD
    assert measured.measurement_attempts == 1
    assert measured.retry_allowed is False
    assert measured.answer_generation_state == "completed"
    assert measured.assessment_state == "deferred"
    assert measured.assessment_reasons == ("provider_http_429",)


def test_browser_measurement_records_one_live_turn_and_all_web_gates(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    readiness = tmp_path / "readiness.json"
    evidence = tmp_path / "browser-evidence.json"
    _corpus(corpus)
    _readiness(readiness)
    prepared = _prepare(
        project=tmp_path,
        corpus_path=corpus,
        readiness_path=readiness,
        run_id="improvement-one",
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure_resource_graph",
        source_revision="a" * 40,
        worktree_dirty=False,
    )
    armed = _arm_browser(project=tmp_path, run_id=prepared.run_id)
    assert armed.retry_allowed is False
    assert _arm_browser(project=tmp_path, run_id=prepared.run_id) == armed
    _private_json(
        evidence,
        {
            "request_count": 1,
            "endpoint_contract": "/chat/stream",
            "run_id": prepared.run_id,
            "case_id": prepared.case_id,
            "question_fingerprint": prepared.question_fingerprint,
            "session_id": f"pantheon-assurance:{prepared.run_id}",
            "purpose": f"conversation-assurance:{prepared.case_id}",
            "request_sequence": 1,
            "request_sha256": "c" * 64,
            "trace_receipt_digest": "d" * 64,
            "run_record_present": True,
            "phase_states": {
                "input": "completed",
                "plan": "completed",
                "collaboration": "completed",
                "evidence": "completed",
                "verification": "completed",
                "answer": "completed",
            },
            "model_trace_enabled": True,
            "omitted_model_calls": 0,
            "expected_call_kinds": ["adaptive-plan", "adaptive-answer", "adaptive-review"],
            "observed_call_kinds": ["adaptive-plan", "adaptive-answer", "adaptive-review"],
            "prompt_manifests_match": True,
            "prompt_profiles_visible": True,
            "system_layer_order_valid": True,
            "untrusted_data_separated": True,
            "preparing_answer_seen": True,
            "early_answer_exposed": False,
            "preparing_answer_overlapped_terminal": False,
            "terminal_transition_completed": True,
            "sensitive_output_detected": False,
            "terminal": {
                "terminal_state": "answered",
                "answer_generation_state": "completed",
                "assessment_state": "completed",
                "assessment_reasons": [],
                "score": 30,
                "verdict": "pass",
            },
        },
    )

    measured = _record_browser_measurement(
        project=tmp_path,
        run_id=prepared.run_id,
        evidence_path=evidence,
        source_revision=prepared.source_revision,
        worktree_dirty=False,
    )

    assert measured.state is ImprovementState.MEASURED
    assert measured.measurement_attempts == 1
    assert measured.run_record_gate.state.value == "passed"
    assert measured.prompt_assembly_gate.state.value == "passed"
    assert measured.preparing_answer_gate.state.value == "passed"


def test_browser_measurement_requires_arm_and_strict_integer_request_count(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus.json"
    readiness = tmp_path / "readiness.json"
    evidence = tmp_path / "browser-evidence.json"
    _corpus(corpus)
    _readiness(readiness)
    prepared = _prepare(
        project=tmp_path,
        corpus_path=corpus,
        readiness_path=readiness,
        run_id="improvement-one",
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure_resource_graph",
        source_revision="a" * 40,
        worktree_dirty=False,
    )
    _private_json(evidence, {"request_count": 1.0, "endpoint_contract": "/chat/stream"})

    with pytest.raises(ValueError, match="not_armed"):
        _record_browser_measurement(
            project=tmp_path,
            run_id=prepared.run_id,
            evidence_path=evidence,
            source_revision=prepared.source_revision,
            worktree_dirty=False,
        )
    _arm_browser(project=tmp_path, run_id=prepared.run_id)
    with pytest.raises(ValueError, match="request_invalid"):
        _record_browser_measurement(
            project=tmp_path,
            run_id=prepared.run_id,
            evidence_path=evidence,
            source_revision=prepared.source_revision,
            worktree_dirty=False,
        )


def test_browser_worker_failure_consumes_attempt_and_classifies_baseline(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus.json"
    readiness = tmp_path / "readiness.json"
    _corpus(corpus)
    _readiness(readiness)
    prepared = _prepare(
        project=tmp_path,
        corpus_path=corpus,
        readiness_path=readiness,
        run_id="improvement-one",
        capability_id="current-resource-state",
        required_functions=("query.resource_state_inventory",),
        expected_authority="azure_resource_graph",
        source_revision="a" * 40,
        worktree_dirty=False,
    )
    _arm_browser(project=tmp_path, run_id=prepared.run_id)

    failed = _record_browser_failure(
        project=tmp_path,
        run_id=prepared.run_id,
        reason="browser_worker_failed",
    )

    assert failed.measurement_attempts == 1
    assert failed.retry_allowed is False
    assert _automatic_failure_class(failed).value == "baseline_failure"


def test_malformed_browser_evidence_consumes_series_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = tmp_path / "readiness.json"
    runtime_env = tmp_path / "runtime.env"
    _readiness(readiness)
    runtime_env.write_text("FDAI_OTHER=value\n", encoding="utf-8")
    runtime_env.chmod(0o600)
    binding = AksBusinessServiceBinding(
        cluster_name="actual-cluster-private",
        provider_ref="/subscriptions/private/resourceGroups/private/providers/"
        "Microsoft.ContainerService/managedClusters/actual-cluster-private",
        resource_id="resource-private",
        business_service_name="actual-checkout-private",
    )
    _prepare_aks_series(
        project=tmp_path,
        readiness_path=readiness,
        runtime_env_path=runtime_env,
        run_prefix="aks-series-one",
        source_revision="a" * 40,
        worktree_dirty=False,
        bindings=(binding,),
    )

    def malformed_worker(command: tuple[str, ...], **_kwargs: object) -> object:
        output = Path(command[command.index("--output") + 1])
        _private_json(output, {})
        return object()

    monkeypatch.setattr(
        "scripts.automation.conversation_assurance_improvement_cli.subprocess.run",
        malformed_worker,
    )

    with pytest.raises(ValueError, match="core_runtime_corpus_not_loaded"):
        _run_aks_browser_series(
            project=tmp_path,
            run_prefix="aks-series-one",
            origin="http://localhost:5273",
            readiness_path=readiness,
            source_revision="a" * 40,
            worktree_dirty=False,
        )
    digest = next(
        line.split("=", 1)[1]
        for line in runtime_env.read_text(encoding="utf-8").splitlines()
        if line.startswith("FDAI_CONVERSATION_ASSURANCE_CORPUS_DIGEST=")
    )
    _readiness(readiness, corpus_digest=digest)
    runs = _run_aks_browser_series(
        project=tmp_path,
        run_prefix="aks-series-one",
        origin="http://localhost:5273",
        readiness_path=readiness,
        source_revision="a" * 40,
        worktree_dirty=False,
    )

    assert len(runs) == 1
    assert runs[0].state is ImprovementState.HELD
    assert runs[0].measurement_attempts == 1
    assert runs[0].retry_allowed is False
    assert runs[0].assessment_reasons == ("browser_worker_failed",)


def test_transcript_measurement_rejects_lossy_assessment_reasons() -> None:
    with pytest.raises(ValueError, match="assessment_reasons_invalid"):
        _measurement_outcome(
            {"state": "held"},
            {
                "case_id": "case-one",
                "terminal_state": "held",
                "assessment_state": "deferred",
                "assessment_reasons": ["provider_http_429", 7],
            },
        )


def test_browser_terminal_requires_each_explicit_state() -> None:
    with pytest.raises(ValueError, match="answer_generation_state_invalid"):
        _terminal_measurement_outcome(
            {
                "terminal_state": "answered",
                "assessment_state": "completed",
                "assessment_reasons": [],
                "score": 30,
                "verdict": "pass",
            }
        )


def test_hardening_round_parser_requires_severity() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "hardening-round",
                "--run-id",
                "run-one",
                "--reviewer-scope",
                "review-one",
                "--finding-count",
                "0",
                "--fixed-count",
                "0",
            ]
        )
