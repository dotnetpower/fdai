"""Deterministic precision and recall evaluation for the owned analysis engine."""

from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.analysis_contracts import CodeSecurityRuleSpec
from fdai.core.security.code_findings.java_analysis import analyze_java_repository
from fdai.core.security.code_findings.python_analysis import analyze_python_repository
from fdai.rule_catalog.code_security_analysis_evaluation import AnalysisEvaluationCorpus

_REVISION = "0" * 40
_DIGEST = "sha256:" + "0" * 64


@dataclass(frozen=True, slots=True)
class AnalysisEvaluationMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    unsupported: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class AnalysisEvaluationReceipt:
    corpus_id: str
    corpus_version: str
    rule_id: str
    rule_version: str
    dev: AnalysisEvaluationMetrics
    holdout: AnalysisEvaluationMetrics
    duration_ms: int
    peak_memory_kib: int


def _metrics(outcomes: list[tuple[bool, bool, bool]]) -> AnalysisEvaluationMetrics:
    true_positive = false_positive = false_negative = true_negative = 0
    for expected, detected, supported in outcomes:
        if not supported:
            continue
        if expected and detected:
            true_positive += 1
        elif detected:
            false_positive += 1
        elif expected:
            false_negative += 1
        else:
            true_negative += 1
    unsupported = sum(not supported for _, _, supported in outcomes)
    reported = true_positive + false_positive
    expected_positive = true_positive + false_negative
    precision = true_positive / reported if reported else 0.0
    recall = true_positive / expected_positive if expected_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return AnalysisEvaluationMetrics(
        true_positive,
        false_positive,
        false_negative,
        true_negative,
        unsupported,
        precision,
        recall,
        f1,
    )


def evaluate_python_analysis(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
) -> AnalysisEvaluationReceipt:
    """Evaluate every frozen case without executing repository code or using the network."""
    if corpus.rule_id != rule.rule_id:
        raise ValueError("evaluation corpus and rule identity differ")
    if corpus.language != "python":
        raise ValueError("Python evaluation requires a Python corpus")
    outcomes: dict[str, list[tuple[bool, bool, bool]]] = {"dev": [], "holdout": []}
    started = time.perf_counter_ns()
    tracemalloc.start()
    try:
        for case in corpus.cases:
            case_root = work_root / case.case_id
            case_root.mkdir(parents=True, exist_ok=False)
            for relative, source in case.files.items():
                path = case_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            result = analyze_python_repository(
                case_root,
                revision=_REVISION,
                build_context_digest=_DIGEST,
                framework_model_digest=rule.digest(),
                rule=rule,
            )
            outcomes[case.split].append(
                (case.vulnerable, bool(result.paths), not result.graph.coverage_limits)
            )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
    return AnalysisEvaluationReceipt(
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        dev=_metrics(outcomes["dev"]),
        holdout=_metrics(outcomes["holdout"]),
        duration_ms=duration_ms,
        peak_memory_kib=peak // 1024,
    )


def evaluate_java_analysis(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
) -> AnalysisEvaluationReceipt:
    """Evaluate a frozen Java corpus through the bounded tree-sitter frontend."""
    if corpus.rule_id != rule.rule_id:
        raise ValueError("evaluation corpus and rule identity differ")
    if corpus.language != "java":
        raise ValueError("Java evaluation requires a Java corpus")
    outcomes: dict[str, list[tuple[bool, bool, bool]]] = {"dev": [], "holdout": []}
    started = time.perf_counter_ns()
    tracemalloc.start()
    try:
        for case in corpus.cases:
            case_root = work_root / case.case_id
            case_root.mkdir(parents=True, exist_ok=False)
            for relative, source in case.files.items():
                path = case_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            result = analyze_java_repository(
                case_root,
                revision=_REVISION,
                build_context_digest=_DIGEST,
                framework_model_digest=rule.digest(),
                rule=rule,
            )
            if result is None:
                outcomes[case.split].append((case.vulnerable, False, False))
            else:
                outcomes[case.split].append(
                    (case.vulnerable, bool(result.paths), not result.graph.coverage_limits)
                )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
    return AnalysisEvaluationReceipt(
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        dev=_metrics(outcomes["dev"]),
        holdout=_metrics(outcomes["holdout"]),
        duration_ms=duration_ms,
        peak_memory_kib=peak // 1024,
    )


__all__ = [
    "AnalysisEvaluationMetrics",
    "AnalysisEvaluationReceipt",
    "evaluate_java_analysis",
    "evaluate_python_analysis",
]
