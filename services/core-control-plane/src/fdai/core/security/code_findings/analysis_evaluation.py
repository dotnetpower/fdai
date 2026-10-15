"""Deterministic precision and recall evaluation for the owned analysis engine."""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from fdai.core.security.code_findings.analysis_contracts import (
    CodeSecurityRuleSpec,
    GraphNodeKind,
)
from fdai.core.security.code_findings.java_analysis import (
    JavaAnalysisResult,
    analyze_java_repository,
)
from fdai.core.security.code_findings.python_analysis import (
    PythonAnalysisResult,
    analyze_python_repository,
)
from fdai.core.security.code_findings.typescript_analysis import (
    TypeScriptAnalysisResult,
    TypeScriptFrontendConfig,
    analyze_typescript_repository,
)
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
    schema_version: str
    corpus_id: str
    corpus_version: str
    corpus_digest: str
    language: str
    rule_id: str
    rule_version: str
    dev: AnalysisEvaluationMetrics
    holdout: AnalysisEvaluationMetrics
    cases: tuple[AnalysisCaseObservation, ...]
    corpus_size: int
    graph_nodes: int
    graph_edges: int
    analyzed_function_share: float
    multi_file_path_recall: float
    framework_coverage: float
    fix_regression_rate: float
    meets_initial_thresholds: bool
    promotion_eligible: bool
    duration_ms: int
    peak_memory_kib: int

    def stable_dict(self) -> dict[str, object]:
        document = asdict(self)
        document.pop("duration_ms")
        document.pop("peak_memory_kib")
        cases = document["cases"]
        if isinstance(cases, tuple):
            for case in cases:
                case.pop("duration_ms")
                case.pop("peak_memory_kib")
            document["cases"] = list(cases)
        return document


@dataclass(frozen=True, slots=True)
class AnalysisCaseObservation:
    case_id: str
    split: str
    vulnerable: bool
    detected: bool
    supported: bool
    graph_nodes: int
    graph_edges: int
    functions: int
    files: int
    path_count: int
    multi_file_paths: int
    framework_sources: int
    duration_ms: int
    peak_memory_kib: int


_AnalysisResult = PythonAnalysisResult | JavaAnalysisResult | TypeScriptAnalysisResult


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


def _evaluate_analysis(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
    analyzer: Callable[[Path], _AnalysisResult | None],
) -> AnalysisEvaluationReceipt:
    if corpus.rule_id != rule.rule_id:
        raise ValueError("evaluation corpus and rule identity differ")
    outcomes: dict[str, list[tuple[bool, bool, bool]]] = {"dev": [], "holdout": []}
    observations: list[AnalysisCaseObservation] = []
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
            case_started = time.perf_counter_ns()
            tracemalloc.reset_peak()
            result = analyzer(case_root)
            _, case_peak = tracemalloc.get_traced_memory()
            case_duration = max(0, (time.perf_counter_ns() - case_started) // 1_000_000)
            detected = result is not None and bool(result.paths)
            supported = result is not None and not result.graph.coverage_limits
            outcomes[case.split].append((case.vulnerable, detected, supported))
            graph = result.graph if result is not None else None
            paths = result.paths if result is not None else ()
            observations.append(
                AnalysisCaseObservation(
                    case_id=case.case_id,
                    split=case.split,
                    vulnerable=case.vulnerable,
                    detected=detected,
                    supported=supported,
                    graph_nodes=len(graph.nodes) if graph is not None else 0,
                    graph_edges=len(graph.edges) if graph is not None else 0,
                    functions=(
                        sum(node.kind is GraphNodeKind.FUNCTION for node in graph.nodes)
                        if graph is not None
                        else 0
                    ),
                    files=(
                        sum(node.kind is GraphNodeKind.FILE for node in graph.nodes)
                        if graph is not None
                        else 0
                    ),
                    path_count=len(paths),
                    multi_file_paths=sum(
                        len({step.span.path for step in path.steps}) > 1 for path in paths
                    ),
                    framework_sources=(
                        sum(node.kind is GraphNodeKind.SOURCE for node in graph.nodes)
                        if graph is not None
                        else 0
                    ),
                    duration_ms=case_duration,
                    peak_memory_kib=case_peak // 1024,
                )
            )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    duration_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
    dev = _metrics(outcomes["dev"])
    holdout = _metrics(outcomes["holdout"])
    supported_observations = [item for item in observations if item.supported]
    total_functions = sum(item.functions for item in observations)
    multi_file_expected = [
        item
        for item, case in zip(observations, corpus.cases, strict=True)
        if case.vulnerable and len(case.files) > 1
    ]
    safe_observations = [item for item in observations if not item.vulnerable]
    meets_initial_thresholds = all(
        metrics.precision >= 0.90 and metrics.recall >= 0.85 and metrics.unsupported == 0
        for metrics in (dev, holdout)
    )
    return AnalysisEvaluationReceipt(
        schema_version="1.0.0",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=corpus.digest(),
        language=corpus.language,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        dev=dev,
        holdout=holdout,
        cases=tuple(observations),
        corpus_size=len(observations),
        graph_nodes=sum(item.graph_nodes for item in observations),
        graph_edges=sum(item.graph_edges for item in observations),
        analyzed_function_share=(
            sum(item.functions for item in supported_observations) / total_functions
            if total_functions
            else 0.0
        ),
        multi_file_path_recall=(
            sum(item.multi_file_paths > 0 for item in multi_file_expected)
            / len(multi_file_expected)
            if multi_file_expected
            else 0.0
        ),
        framework_coverage=(
            sum(item.framework_sources > 0 for item in observations) / len(observations)
            if observations
            else 0.0
        ),
        fix_regression_rate=(
            sum(not item.detected and item.supported for item in safe_observations)
            / len(safe_observations)
            if safe_observations
            else 0.0
        ),
        meets_initial_thresholds=meets_initial_thresholds,
        promotion_eligible=False,
        duration_ms=duration_ms,
        peak_memory_kib=peak // 1024,
    )


def evaluate_python_analysis(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
) -> AnalysisEvaluationReceipt:
    """Evaluate every frozen Python case without executing repository code or using network."""
    if corpus.language != "python":
        raise ValueError("Python evaluation requires a Python corpus")
    return _evaluate_analysis(
        corpus,
        rule,
        work_root,
        lambda case_root: analyze_python_repository(
            case_root,
            revision=_REVISION,
            build_context_digest=_DIGEST,
            framework_model_digest=rule.digest(),
            rule=rule,
        ),
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
    return _evaluate_analysis(
        corpus,
        rule,
        work_root,
        lambda case_root: analyze_java_repository(
            case_root,
            revision=_REVISION,
            build_context_digest=_DIGEST,
            framework_model_digest=rule.digest(),
            rule=rule,
        ),
    )


def evaluate_typescript_analysis(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
    config: TypeScriptFrontendConfig,
) -> AnalysisEvaluationReceipt:
    """Evaluate every frozen TypeScript case through the pinned Compiler API frontend."""
    if corpus.language != "typescript":
        raise ValueError("TypeScript evaluation requires a TypeScript corpus")
    return _evaluate_analysis(
        corpus,
        rule,
        work_root,
        lambda case_root: analyze_typescript_repository(
            case_root,
            revision=_REVISION,
            build_context_digest=_DIGEST,
            framework_model_digest=rule.digest(),
            rule=rule,
            config=config,
        ),
    )


__all__ = [
    "AnalysisEvaluationMetrics",
    "AnalysisEvaluationReceipt",
    "AnalysisCaseObservation",
    "evaluate_java_analysis",
    "evaluate_python_analysis",
    "evaluate_typescript_analysis",
]
