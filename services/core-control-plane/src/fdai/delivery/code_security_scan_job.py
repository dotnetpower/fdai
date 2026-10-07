"""Deterministic-lane scan job: acquire, scan in the sandbox, canonicalize, and review.

The job runs every catalog scanner that the deployment binds to an executable, against the exact
acquired revision, inside the bubblewrap sandbox. It writes each scanner's SARIF and the coverage
receipt under the job's work root, builds canonical issues and the strict review package, and
optionally publishes the package through Heimdall. Coverage is complete only when every required
scanner was bound, completed inside the sandbox, and produced valid SARIF; anything else is
recorded as a coverage limit and makes the review ``coverage_incomplete``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from fdai.core.security.code_findings import (
    AnalysisContext,
    CodeSecurityIssue,
    Lane,
    SarifIngestContext,
    SarifIngestError,
    SarifIngestResult,
    build_issues,
    ingest_sarif,
)
from fdai.core.security.code_findings.lens import (
    LensLaneReport,
    LensLaneUnavailableError,
    run_lens_lane,
)
from fdai.core.security.code_findings.models import Occurrence
from fdai.core.security.code_findings.receipts import build_receipt, receipt_to_dict
from fdai.core.security.code_findings.review_signal import build_review_package
from fdai.core.security.code_findings.verification import ScanCoverageReceipt
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, ScannerRunResult
from fdai.rule_catalog.code_security import CodeSecurityCatalog, Exposure
from fdai.rule_catalog.code_security_lenses import LensCatalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog
from fdai.shared.providers.code_security_lens import CodeSecurityLensModel


class ReviewPublisher(Protocol):
    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool: ...


@dataclass(frozen=True, slots=True)
class ScanJobConfig:
    repository: str
    revision: str
    repository_alias: str
    work_root: Path
    executables: Mapping[str, Path]
    rules_dir: Path
    cache_dir: Path | None = None
    exposure: Exposure = Exposure.UNKNOWN
    required_scanners: frozenset[str] | None = None
    known_exploited: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ScanJobResult:
    revision: str
    tree_id: str
    issues: tuple[CodeSecurityIssue, ...]
    receipt: ScanCoverageReceipt
    package: dict[str, object]
    runs: tuple[ScannerRunResult, ...]
    coverage_limits: tuple[str, ...]
    published: bool
    artifact_dir: Path
    sarif_files: tuple[Path, ...]
    lens_report: LensLaneReport | None = None


async def run_scan_job(
    config: ScanJobConfig,
    *,
    catalog: CodeSecurityCatalog,
    scanners: ScannerCatalog,
    acquirer: GitSourceAcquirer,
    sandbox: BubblewrapScannerSandbox,
    publisher: ReviewPublisher | None = None,
    lens_catalog: LensCatalog | None = None,
    lens_models: Sequence[CodeSecurityLensModel] = (),
) -> ScanJobResult:
    """Run the deterministic lane, and the optional LLM lens lane, for one revision.

    Lens findings are inert hypotheses. Lens gaps are recorded as lens notes, not as
    deterministic coverage limits, because the lens lane is optional.
    """
    source = acquirer.acquire(config.repository, config.revision)
    artifacts = config.work_root / "scans" / config.revision
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    required = config.required_scanners or frozenset(scanners.scanners)
    limits: list[str] = []
    runs: list[ScannerRunResult] = []
    ingested: list[SarifIngestResult] = []
    observed: dict[str, bool] = {}
    sarif_files: list[Path] = []
    for scanner_id, spec in sorted(scanners.scanners.items()):
        executable = config.executables.get(scanner_id)
        if executable is None:
            if scanner_id in required:
                limits.append(f"required scanner {scanner_id} is not installed")
            continue
        if "cache" in spec.mounts and config.cache_dir is None:
            limits.append(f"scanner {scanner_id} needs an offline cache and none is configured")
            observed[spec.producer] = False
            continue
        run = await sandbox.run(
            scanner_id,
            spec,
            executable,
            source.path,
            rules=config.rules_dir if "rules" in spec.mounts else None,
            cache=config.cache_dir if "cache" in spec.mounts else None,
        )
        runs.append(run)
        observed[spec.producer] = run.completed
        if not run.completed:
            reason = (
                "timed out"
                if run.timed_out
                else "truncated"
                if run.truncated
                else (f"exited {run.exit_code}")
            )
            limits.append(f"scanner {scanner_id} {reason}")
            continue
        path = artifacts / f"{scanner_id}.sarif"
        path.write_bytes(run.stdout)
        sarif_files.append(path)
        try:
            ingested.append(
                ingest_sarif(
                    run.stdout,
                    SarifIngestContext(
                        lane=Lane.DETERMINISTIC,
                        revision=config.revision,
                        source_roots=("/source", str(source.path)),
                    ),
                )
            )
        except SarifIngestError as exc:
            observed[spec.producer] = False
            limits.append(f"scanner {scanner_id} produced invalid SARIF: {exc}")
    occurrences: list[Occurrence] = [occ for result in ingested for occ in result.occurrences]
    lens_report: LensLaneReport | None = None
    lens_notes: list[str] = []
    if lens_catalog is not None and lens_models:
        try:
            lens_occurrences, lens_report = await run_lens_lane(
                source.path, lens_catalog, lens_models, revision=config.revision
            )
            occurrences.extend(lens_occurrences)
            lens_notes = list(lens_report.notes)
        except LensLaneUnavailableError as exc:
            lens_notes = [str(exc)]
    issues = build_issues(
        occurrences,
        catalog,
        AnalysisContext(
            revision=config.revision,
            exposure=config.exposure,
            known_exploited=config.known_exploited,
        ),
    )
    receipt = build_receipt(
        config.revision,
        catalog.version_stamp(),
        ingested,
        rules_versions=_rules_versions(ingested, scanners, rules_digest(config.rules_dir)),
        full_repository=frozenset(p for p, done in observed.items() if done),
        observed_completion=observed,
    )
    complete = (
        not limits
        and bool(receipt.runs)
        and all(run.completed is True and not run.truncated for run in receipt.runs)
    )
    package = build_review_package(
        issues,
        repository_alias=config.repository_alias,
        revision=config.revision,
        exposure=config.exposure,
        coverage_complete=complete,
    )
    (artifacts / "receipt.json").write_text(
        json.dumps(
            {
                "receipt": receipt_to_dict(receipt),
                "coverage_limits": limits,
                "tree_id": source.tree_id,
                "lens": {
                    "ran": lens_report is not None,
                    "complete": lens_report.complete if lens_report else False,
                    "kept": lens_report.kept if lens_report else 0,
                    "model_calls": lens_report.model_calls if lens_report else 0,
                    "notes": lens_notes,
                },
            },
            indent=2,
        )
        + "\n"
    )
    (artifacts / "review.json").write_text(json.dumps(package, indent=2) + "\n")
    published = await publisher.publish_code_security_drift(package) if publisher else False
    return ScanJobResult(
        revision=config.revision,
        tree_id=source.tree_id,
        issues=issues,
        receipt=receipt,
        package=package,
        runs=tuple(runs),
        coverage_limits=tuple(limits),
        published=published,
        artifact_dir=artifacts,
        sarif_files=tuple(sarif_files),
        lens_report=lens_report,
    )


def rules_digest(rules_dir: Path) -> str:
    """Return a digest over the rule pack's YAML files (path and content)."""
    digest = hashlib.sha256()
    for path in sorted(rules_dir.rglob("*.y*ml")):
        digest.update(path.relative_to(rules_dir).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def _rules_versions(
    ingested: Sequence[SarifIngestResult], scanners: ScannerCatalog, digest: str
) -> dict[str, str]:
    """Bind each producer's rules version to its tool version and, if used, the rule pack."""
    versions: dict[str, set[str]] = {}
    for result in ingested:
        for run in result.runs:
            versions.setdefault(run.producer, set()).add(run.version or "unknown")
    resolved = {}
    for scanner_id, spec in scanners.scanners.items():
        tool = "+".join(sorted(versions.get(spec.producer, {"unknown"})))
        suffix = f":rules-{digest}" if "rules" in spec.mounts else ""
        resolved[spec.producer] = f"{scanner_id}:{tool}{suffix}"
    return resolved


def sarif_specs(result: ScanJobResult) -> Sequence[str]:
    """Return ``FILE:LANE`` arguments for exporting a pack from this job's SARIF."""
    return [f"{path}:deterministic" for path in result.sarif_files]


__all__ = [
    "ReviewPublisher",
    "ScanJobConfig",
    "ScanJobResult",
    "rules_digest",
    "run_scan_job",
    "sarif_specs",
]
