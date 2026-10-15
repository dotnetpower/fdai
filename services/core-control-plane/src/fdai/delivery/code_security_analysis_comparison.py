"""Same-condition comparison of current, owned, and external analysis engines."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import yaml

from fdai.core.security.code_findings.analysis_contracts import CodeSecurityRuleSpec
from fdai.core.security.code_findings.analysis_evaluation import (
    AnalysisEvaluationMetrics,
    analysis_evaluation_metrics,
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
from fdai.core.security.code_findings.verifier_evaluation import (
    LabeledLocation,
    LocationOutcome,
)
from fdai.delivery.code_security_verifier_eval import _python_outcomes, _taint_outcomes
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_analysis_evaluation import (
    AnalysisEvaluationCase,
    AnalysisEvaluationCorpus,
    load_analysis_evaluation_corpus,
)
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog

_REVISION = "0" * 40
_DIGEST = "sha256:" + "0" * 64
_WEAKNESS_BY_RULE = {
    "fdai.python.sql-injection": "sql_injection",
    "fdai.python.command-injection": "command_injection",
    "fdai.python.path-traversal": "path_traversal",
    "fdai.typescript.sql-injection": "sql_injection",
    "fdai.typescript.command-injection": "command_injection",
    "fdai.typescript.path-traversal": "path_traversal",
}


@dataclass(frozen=True, slots=True)
class ComparisonCaseObservation:
    case_id: str
    split: str
    vulnerable: bool
    detected: bool
    supported: bool
    duration_ms: int
    peak_memory_kib: int


@dataclass(frozen=True, slots=True)
class ComparisonEngineReceipt:
    engine: Literal["current-verifier", "owned-engine", "external-baseline"]
    implementation: str
    version: str
    available: bool
    dev: AnalysisEvaluationMetrics
    holdout: AnalysisEvaluationMetrics
    cases: tuple[ComparisonCaseObservation, ...]
    duration_ms: int
    peak_memory_kib: int
    graph_nodes: int = 0
    graph_edges: int = 0
    analyzed_function_share: float = 0.0
    framework_coverage: float = 0.0


@dataclass(frozen=True, slots=True)
class AnalysisComparisonReceipt:
    ok: bool
    kind: str
    schema_version: str
    corpus_id: str
    corpus_version: str
    corpus_digest: str
    language: str
    rule_id: str
    source_files: int
    source_bytes: int
    engines: tuple[ComparisonEngineReceipt, ...]
    parity_claimed: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def stable_dict(self) -> dict[str, object]:
        document = self.as_dict()
        engines = document["engines"]
        if isinstance(engines, tuple):
            for engine in engines:
                engine.pop("duration_ms")
                engine.pop("peak_memory_kib")
                for case in engine["cases"]:
                    case.pop("duration_ms")
                    case.pop("peak_memory_kib")
            document["engines"] = list(engines)
        return document

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.stable_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ComparisonConfig:
    catalog_root: Path
    external_engine: Path | None = None
    external_rules: Path | None = None
    typescript_frontend: TypeScriptFrontendConfig | None = None


@dataclass(frozen=True, slots=True)
class _MeasuredOutcome:
    detected: bool
    supported: bool
    duration_ms: int
    peak_memory_kib: int
    graph_nodes: int = 0
    graph_edges: int = 0
    functions: int = 0
    framework_sources: int = 0
    frontend_version: str = ""


def add_analysis_comparison_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = sub.add_parser(
        "evaluate-analysis-comparison",
        help="compare current, owned, and external analyzers on identical local cases",
    )
    command.add_argument("--catalog-root", required=True)
    command.add_argument("--corpus", default="python-sql-injection")
    command.add_argument("--work-root", required=True)
    command.add_argument("--external-engine")
    command.add_argument("--typescript-node")
    command.add_argument("--typescript-frontend")
    command.add_argument("--output")


def _measure(operation: Callable[[], tuple[bool, bool]]) -> _MeasuredOutcome:
    started = time.perf_counter_ns()
    tracemalloc.start()
    try:
        detected, supported = operation()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return _MeasuredOutcome(
        detected,
        supported,
        max(0, (time.perf_counter_ns() - started) // 1_000_000),
        peak // 1024,
    )


def _case_locations(
    case: AnalysisEvaluationCase,
    weakness: str,
    verifier: Literal["python", "taint"],
) -> tuple[LabeledLocation, ...]:
    return tuple(
        LabeledLocation(
            source_id=case.case_id,
            path=path,
            line=None,
            weakness_class=weakness,
            verifier=verifier,
            vulnerable=case.vulnerable,
            split=case.split,
        )
        for path in sorted(case.files)
    )


def _current_case(
    root: Path,
    case: AnalysisEvaluationCase,
    weakness: str | None,
    config: ComparisonConfig,
) -> _MeasuredOutcome:
    if case.files and all(Path(path).suffix == ".py" for path in case.files) and weakness:
        catalog = load_code_security_catalog(config.catalog_root)
        locations = _case_locations(case, weakness, "python")

        def verify() -> tuple[bool, bool]:
            outcomes = _python_outcomes(root, locations, catalog, config.catalog_root, _REVISION)
            values = tuple(outcomes.values())
            return (
                LocationOutcome.VERIFIED in values,
                any(value is not LocationOutcome.UNSUPPORTED for value in values),
            )

        return _measure(verify)
    return _MeasuredOutcome(False, False, 0, 0)


def _owned_case(
    root: Path,
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    config: ComparisonConfig,
) -> _MeasuredOutcome:
    started = time.perf_counter_ns()
    tracemalloc.start()
    result: PythonAnalysisResult | TypeScriptAnalysisResult | JavaAnalysisResult | None
    try:
        if corpus.language == "python":
            result = analyze_python_repository(
                root,
                revision=_REVISION,
                build_context_digest=_DIGEST,
                framework_model_digest=rule.digest(),
                rule=rule,
            )
        elif corpus.language == "typescript" and config.typescript_frontend is not None:
            result = analyze_typescript_repository(
                root,
                revision=_REVISION,
                build_context_digest=_DIGEST,
                framework_model_digest=rule.digest(),
                rule=rule,
                config=config.typescript_frontend,
            )
        elif corpus.language == "java":
            result = analyze_java_repository(
                root,
                revision=_REVISION,
                build_context_digest=_DIGEST,
                framework_model_digest=rule.digest(),
                rule=rule,
            )
        else:
            result = None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    graph = result.graph if result is not None else None
    nodes = graph.nodes if graph is not None else ()
    frontend = (
        ",".join(f"{key}@{value}" for key, value in sorted(graph.frontend_versions.items()))
        if graph is not None
        else "unavailable"
    )
    return _MeasuredOutcome(
        detected=result is not None and bool(result.paths),
        supported=graph is not None and not graph.coverage_limits,
        duration_ms=max(0, (time.perf_counter_ns() - started) // 1_000_000),
        peak_memory_kib=peak // 1024,
        graph_nodes=len(nodes),
        graph_edges=len(graph.edges) if graph is not None else 0,
        functions=sum(node.kind.value == "function" for node in nodes),
        framework_sources=sum(node.kind.value == "source" for node in nodes),
        frontend_version=frontend,
    )


def _external_rule_ids(root: Path) -> frozenset[str]:
    identities: set[str] = set()
    for path in sorted(root.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("rules"), list):
            continue
        for item in document["rules"]:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                identities.add(item["id"])
    return frozenset(identities)


def _external_case(
    root: Path,
    case: AnalysisEvaluationCase,
    weakness: str | None,
    config: ComparisonConfig,
    supported_rules: frozenset[str],
) -> _MeasuredOutcome:
    engine = config.external_engine
    rules = config.external_rules
    if engine is None or rules is None or weakness is None:
        return _MeasuredOutcome(False, False, 0, 0)
    locations = _case_locations(case, weakness, "taint")
    if not locations or locations[0].key not in supported_rules:
        return _MeasuredOutcome(False, False, 0, 0)

    def scan() -> tuple[bool, bool]:
        outcomes, _ = _taint_outcomes(str(engine), rules, root, locations)
        values = tuple(outcomes.values())
        return (
            LocationOutcome.VERIFIED in values,
            any(value is not LocationOutcome.UNSUPPORTED for value in values),
        )

    return _measure(scan)


def _engine_version(engine: Path | None) -> str:
    if engine is None:
        return "unavailable"
    completed = subprocess.run(  # noqa: S603 - caller binds the exact trusted executable
        [str(engine), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SEMGREP_ENABLE_VERSION_CHECK": "0",
        },
    )
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return text[0][:200] if completed.returncode == 0 and text else "unknown"


def _engine_receipt(
    name: Literal["current-verifier", "owned-engine", "external-baseline"],
    implementation: str,
    version: str,
    cases: tuple[AnalysisEvaluationCase, ...],
    outcomes: tuple[_MeasuredOutcome, ...],
) -> ComparisonEngineReceipt:
    by_split = {
        split: [
            (case.vulnerable, outcome.detected, outcome.supported)
            for case, outcome in zip(cases, outcomes, strict=True)
            if case.split == split
        ]
        for split in ("dev", "holdout")
    }
    functions = sum(item.functions for item in outcomes)
    supported_functions = sum(item.functions for item in outcomes if item.supported)
    return ComparisonEngineReceipt(
        engine=name,
        implementation=implementation,
        version=version,
        available=any(item.supported for item in outcomes),
        dev=analysis_evaluation_metrics(by_split["dev"]),
        holdout=analysis_evaluation_metrics(by_split["holdout"]),
        cases=tuple(
            ComparisonCaseObservation(
                case.case_id,
                case.split,
                case.vulnerable,
                outcome.detected,
                outcome.supported,
                outcome.duration_ms,
                outcome.peak_memory_kib,
            )
            for case, outcome in zip(cases, outcomes, strict=True)
        ),
        duration_ms=sum(item.duration_ms for item in outcomes),
        peak_memory_kib=max((item.peak_memory_kib for item in outcomes), default=0),
        graph_nodes=sum(item.graph_nodes for item in outcomes),
        graph_edges=sum(item.graph_edges for item in outcomes),
        analyzed_function_share=supported_functions / functions if functions else 0.0,
        framework_coverage=(
            sum(item.framework_sources > 0 for item in outcomes) / len(outcomes)
            if outcomes
            else 0.0
        ),
    )


def compare_analysis_engines(
    corpus: AnalysisEvaluationCorpus,
    rule: CodeSecurityRuleSpec,
    work_root: Path,
    config: ComparisonConfig,
) -> AnalysisComparisonReceipt:
    """Run every engine over the same materialized cases without executing source code."""
    if corpus.rule_id != rule.rule_id:
        raise ValueError("comparison corpus and rule identity differ")
    catalog_root = config.catalog_root.resolve(strict=True)
    external_engine = (
        config.external_engine.resolve(strict=True) if config.external_engine is not None else None
    )
    external_rules = (
        config.external_rules.resolve(strict=True) if config.external_rules is not None else None
    )
    config = ComparisonConfig(
        catalog_root=catalog_root,
        external_engine=external_engine,
        external_rules=external_rules,
        typescript_frontend=config.typescript_frontend,
    )
    work_root.mkdir(parents=True, exist_ok=False)
    weakness = _WEAKNESS_BY_RULE.get(rule.rule_id)
    supported_rules = (
        _external_rule_ids(config.external_rules)
        if config.external_rules is not None
        else frozenset()
    )
    current: list[_MeasuredOutcome] = []
    owned: list[_MeasuredOutcome] = []
    external: list[_MeasuredOutcome] = []
    for case in corpus.cases:
        case_root = work_root / case.case_id
        case_root.mkdir()
        for relative, source in case.files.items():
            destination = case_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")
        current.append(_current_case(case_root, case, weakness, config))
        owned.append(_owned_case(case_root, corpus, rule, config))
        external.append(_external_case(case_root, case, weakness, config, supported_rules))
    verifier = load_verifier_catalog(
        config.catalog_root,
        frozenset(load_code_security_catalog(config.catalog_root).weakness_classes.classes),
    )
    owned_versions = sorted({item.frontend_version for item in owned})
    engine_path = config.external_engine
    receipts = (
        _engine_receipt(
            "current-verifier", "fdai-python-ast", verifier.version, corpus.cases, tuple(current)
        ),
        _engine_receipt(
            "owned-engine",
            "fdai-common-graph",
            ";".join(owned_versions),
            corpus.cases,
            tuple(owned),
        ),
        _engine_receipt(
            "external-baseline",
            engine_path.name if engine_path is not None else "unavailable",
            _engine_version(engine_path),
            corpus.cases,
            tuple(external),
        ),
    )
    return AnalysisComparisonReceipt(
        ok=True,
        kind="fdai.code-security.analysis-comparison-receipt",
        schema_version="1.0.0",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=corpus.digest(),
        language=corpus.language,
        rule_id=rule.rule_id,
        source_files=sum(len(case.files) for case in corpus.cases),
        source_bytes=sum(
            len(source.encode("utf-8")) for case in corpus.cases for source in case.files.values()
        ),
        engines=receipts,
    )


def run_analysis_comparison(args: argparse.Namespace) -> dict[str, object]:
    """Load one catalog corpus, run the comparison, and optionally write its receipt."""
    catalog_root = Path(args.catalog_root)
    corpus = load_analysis_evaluation_corpus(catalog_root, args.corpus)
    rule = next(
        (item for item in load_analysis_rules(catalog_root) if item.rule_id == corpus.rule_id),
        None,
    )
    if rule is None:
        raise ValueError(f"analysis rule {corpus.rule_id} is unavailable")
    node = getattr(args, "typescript_node", None)
    frontend = getattr(args, "typescript_frontend", None)
    if bool(node) != bool(frontend):
        raise ValueError("TypeScript comparison requires both node and frontend bindings")
    node_path = Path(str(node)) if node else None
    frontend_path = Path(str(frontend)) if frontend else None
    typescript = (
        TypeScriptFrontendConfig(node=node_path, script=frontend_path)
        if node_path is not None and frontend_path is not None
        else None
    )
    engine = getattr(args, "external_engine", None)
    receipt = compare_analysis_engines(
        corpus,
        rule,
        Path(args.work_root),
        ComparisonConfig(
            catalog_root=catalog_root,
            external_engine=Path(engine) if engine else None,
            external_rules=catalog_root / "rules" / "verify" if engine else None,
            typescript_frontend=typescript,
        ),
    )
    document = receipt.as_dict()
    output = getattr(args, "output", None)
    if output:
        Path(output).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


__all__ = [
    "AnalysisComparisonReceipt",
    "ComparisonCaseObservation",
    "ComparisonConfig",
    "ComparisonEngineReceipt",
    "add_analysis_comparison_command",
    "compare_analysis_engines",
    "run_analysis_comparison",
]
