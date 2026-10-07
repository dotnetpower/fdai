"""Run the weakness verifiers against the real-code verifier corpus and write a receipt.

Each corpus source is acquired at its exact commit, read-only, with the same acquirer the scan job
uses. The Python AST verifier runs in process on synthetic issues at the labeled locations. The
taint rules run through the configured Opengrep or Semgrep engine with network metrics disabled.
Neither path executes project code. Taint hits outside the labeled set are listed for review and
never counted toward precision.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane, Occurrence, SourceLocation
from fdai.core.security.code_findings.verifier import VerifierOutcome, verify_issues
from fdai.core.security.code_findings.verifier_evaluation import (
    LabeledLocation,
    LocationOutcome,
    locations_from_mapping,
    verifier_metrics,
)
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import CodeSecurityCatalog, load_code_security_catalog
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog

_ENGINE_TIMEOUT_SECONDS = 900


def add_verifier_evaluation_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    root = repo_asset_root() / "rule-catalog" / "code-security"
    command = sub.add_parser(
        "evaluate-verifiers", help="measure verifier precision on pinned public projects"
    )
    command.add_argument("--corpus", default=str(root / "evaluation" / "verifier-corpus.yaml"))
    command.add_argument("--work-root", required=True)
    command.add_argument("--engine", required=True, help="opengrep or semgrep executable")
    command.add_argument("--output", help="write the receipt to this file")
    command.add_argument("--catalog-root", default=str(root))


def _python_outcomes(
    tree: Path,
    locations: Sequence[LabeledLocation],
    catalog: CodeSecurityCatalog,
    catalog_root: Path,
    revision: str,
) -> dict[LabeledLocation, LocationOutcome]:
    if not locations:
        return {}
    occurrences = []
    for index, location in enumerate(locations):
        entry = catalog.weakness_classes.classes[location.weakness_class]
        occurrences.append(
            Occurrence(
                occurrence_id=f"label-{index}",
                producer="verifier-corpus",
                producer_version="1",
                lane=Lane.DETERMINISTIC,
                scan_digest="sha256:verifier-corpus",
                revision=revision,
                rule_id="label",
                location=SourceLocation(location.path, location.line),
                cwe_ids=(entry.cwe[0],),
            )
        )
    issues = build_issues(occurrences, catalog, AnalysisContext(revision=revision))
    verifiers = load_verifier_catalog(catalog_root, frozenset(catalog.weakness_classes.classes))
    results = {r.issue_id: r for r in verify_issues(tree, issues, verifiers, revision=revision)}
    outcomes: dict[LabeledLocation, LocationOutcome] = {}
    for location in locations:
        issue = next(
            i
            for i in issues
            if i.fix_site.path == location.path and i.fix_site.start_line == location.line
        )
        result = results[issue.issue_id]
        outcomes[location] = (
            LocationOutcome.VERIFIED
            if result.outcome is VerifierOutcome.VERIFIED
            else LocationOutcome.UNSUPPORTED
            if result.outcome is VerifierOutcome.UNSUPPORTED
            else LocationOutcome.NOT_VERIFIED
        )
    return outcomes


def _engine_scan(engine: str, rules: Path, tree: Path) -> Mapping[str, Any]:
    proc = subprocess.run(  # noqa: S603 - fixed argv over an acquired read-only tree
        [engine, "scan", "--metrics=off", "--quiet", "--json", "--config", str(rules), "."],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=_ENGINE_TIMEOUT_SECONDS,
        check=False,
    )
    try:
        document = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"engine produced no JSON (exit {proc.returncode})") from exc
    if not isinstance(document, dict):
        raise RuntimeError("engine output is not a JSON object")
    return document


def _relative(path: str) -> str:
    return path.removeprefix("./")


def _taint_outcomes(
    engine: str, rules: Path, tree: Path, locations: Sequence[LabeledLocation]
) -> tuple[dict[LabeledLocation, LocationOutcome], list[dict[str, object]]]:
    if not locations:
        return {}, []
    document = _engine_scan(engine, rules, tree)
    hits = {
        (
            str(item["check_id"]).rsplit("fdai.verify.", 1)[-1],
            _relative(str(item["path"])),
            int(item["start"]["line"]),
        )
        for item in document.get("results", [])
        if "fdai.verify." in str(item.get("check_id", ""))
    }
    broken = {
        _relative(str(error["path"]))
        for error in document.get("errors", [])
        if isinstance(error, Mapping) and error.get("path")
    }
    outcomes: dict[LabeledLocation, LocationOutcome] = {}
    labeled: set[tuple[str, str, int]] = set()
    for location in locations:
        rule = location.key.removeprefix("fdai.verify.")
        labeled.add((rule, location.path, location.line))
        if (rule, location.path, location.line) in hits:
            outcomes[location] = LocationOutcome.VERIFIED
        elif location.path in broken:
            outcomes[location] = LocationOutcome.UNSUPPORTED
        else:
            outcomes[location] = LocationOutcome.NOT_VERIFIED
    unlabeled = [
        {"rule": f"fdai.verify.{rule}", "path": path, "line": line}
        for rule, path, line in sorted(hits - labeled)
    ]
    return outcomes, unlabeled


def evaluate_verifiers(args: argparse.Namespace) -> dict[str, object]:
    catalog_root = Path(args.catalog_root)
    catalog = load_code_security_catalog(catalog_root)
    raw = yaml.safe_load(Path(args.corpus).read_text(encoding="utf-8"))
    header, locations = locations_from_mapping(raw)
    acquirer = GitSourceAcquirer(Path(args.work_root).resolve())
    outcomes: dict[LabeledLocation, LocationOutcome] = {}
    unlabeled: list[dict[str, object]] = []
    for source in header["sources"]:  # type: ignore[attr-defined]
        source_id = str(source["id"])
        acquired = acquirer.acquire(str(source["repository"]), str(source["commit"]))
        mine = [location for location in locations if location.source_id == source_id]
        outcomes.update(
            _python_outcomes(
                acquired.path,
                [item for item in mine if item.verifier == "python"],
                catalog,
                catalog_root,
                str(source["commit"]),
            )
        )
        taint, extra = _taint_outcomes(
            args.engine,
            catalog_root / "rules" / "verify",
            acquired.path,
            [item for item in mine if item.verifier == "taint"],
        )
        outcomes.update(taint)
        unlabeled.extend({"source": source_id, **item} for item in extra)
    metrics = verifier_metrics(
        locations,
        outcomes,
        precision_floor=float(header["precision_floor"]),  # type: ignore[arg-type]
        min_true_positives=int(header["min_true_positives"]),  # type: ignore[call-overload]
    )
    receipt: dict[str, object] = {
        "ok": True,
        "kind": "fdai.code-security.verifier-evaluation-receipt",
        "corpus": header,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "verifiers": [item.as_dict() for item in metrics],
        "promoted": sorted(item.key for item in metrics if item.promoted),
        "shadow": sorted(item.key for item in metrics if not item.promoted),
        "unlabeled_verified": unlabeled,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


__all__ = ["add_verifier_evaluation_command", "evaluate_verifiers"]
