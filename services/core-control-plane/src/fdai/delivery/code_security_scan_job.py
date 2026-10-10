"""Deterministic-lane scan job: acquire, scan in the sandbox, canonicalize, and review.

The job runs every catalog scanner that the deployment binds to an executable, against the exact
acquired revision, inside the bubblewrap sandbox. It writes each scanner's SARIF and the coverage
receipt under the job's work root, builds canonical issues and the strict review package, and
optionally publishes the package through Heimdall. Coverage is complete only when every required
scanner was bound, completed inside the sandbox, and produced valid SARIF; anything else is
recorded as a coverage limit and makes the review ``coverage_incomplete``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
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
from fdai.core.security.code_findings.review_signal import ReviewSource, build_review_package
from fdai.core.security.code_findings.verification import ScanCoverageReceipt
from fdai.core.security.code_findings.verifier import (
    VerifierResult,
    taint_rule_verifications,
    verified_confidence,
    verify_issues,
)
from fdai.delivery.code_security_acquire import GitSourceAcquirer
from fdai.delivery.code_security_prepared_source import PreparedSource
from fdai.delivery.code_security_prove import ProofResult, prove_issues, proven_confidence
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, ScannerRunResult
from fdai.rule_catalog.code_security import CodeSecurityCatalog, Exposure
from fdai.rule_catalog.code_security_lenses import LensCatalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog
from fdai.rule_catalog.code_security_verifiers import VerifierCatalog
from fdai.shared.providers.code_security_lens import CodeSecurityLensModel


class ReviewPublisher(Protocol):
    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool: ...


@dataclass(frozen=True, slots=True)
class ScanJobConfig:
    """One scan target and its bindings.

    ``local_path`` scans a local folder instead of ``repository`` at ``revision``: its ``HEAD``
    commit, or with ``include_uncommitted`` a content-addressed snapshot of its working files.
    ``source`` records where the code came from and what started the scan; its revision kind is
    taken from the acquisition, never from the caller.
    """

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
    local_path: Path | None = None
    include_uncommitted: bool = False
    source: ReviewSource | None = None


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
    verifier_results: tuple[VerifierResult, ...] = ()
    proof_results: tuple[ProofResult, ...] = ()
    revision_kind: str = "commit"


async def run_scan_job(
    config: ScanJobConfig,
    *,
    catalog: CodeSecurityCatalog,
    scanners: ScannerCatalog,
    acquirer: GitSourceAcquirer | None,
    sandbox: BubblewrapScannerSandbox,
    prepared_source: PreparedSource | None = None,
    publisher: ReviewPublisher | None = None,
    lens_catalog: LensCatalog | None = None,
    lens_models: Sequence[CodeSecurityLensModel] = (),
    verifier_catalog: VerifierCatalog | None = None,
    prove_python: Path | None = None,
    prove_runtimes: Mapping[str, Path] | None = None,
) -> ScanJobResult:
    """Run the deterministic lane, and the optional LLM lens lane, for one revision.

    Lens findings are inert hypotheses. Lens gaps are recorded as lens notes, not as
    deterministic coverage limits, because the lens lane is optional. When a verifier catalog is
    given, deterministic weakness verifiers run on the same acquired tree and raise confirmed
    issues to ``verified`` confidence; they never change severity or close an issue. When
    ``prove_python`` or ``prove_runtimes`` is set, the opt-in proof lane reproduces verified issues
    of each language with a runtime in a disposable sandbox and raises reproduced ones to
    ``proven``.

    ``prepared_source`` replaces acquisition for the credential-free input boundary. It requires
    matching attribution, forbids acquisition and live publication/lenses, and verifies input
    before scanning and before writing the final review. The transport does not attest completion.
    """
    if prepared_source is not None:
        if acquirer is not None or config.local_path is not None or config.repository:
            raise ValueError("prepared scanning cannot also acquire source")
        if config.revision != prepared_source.acquired.revision:
            raise ValueError("prepared revision does not match the scan")
        if (
            config.repository_alias != prepared_source.repository_alias
            or config.source != prepared_source.source
        ):
            raise ValueError("prepared attribution does not match the scan")
        if publisher is not None or lens_models:
            raise ValueError("prepared scanning cannot publish or call live lenses")
        prepared_source.verify_tree()
        source = prepared_source.acquired
    else:
        if acquirer is None:
            raise ValueError("scanning requires a source acquirer")
        source = (
            await asyncio.to_thread(
                acquirer.acquire_path,
                config.local_path,
                include_uncommitted=config.include_uncommitted,
            )
            if config.local_path is not None
            else await asyncio.to_thread(
                acquirer.acquire,
                config.repository,
                config.revision,
            )
        )
    revision = source.revision
    artifacts = config.work_root / "scans" / revision
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
                        revision=revision,
                        source_roots=("/source", str(source.path)),
                        producer=spec.producer,
                    ),
                )
            )
        except SarifIngestError as exc:
            observed[spec.producer] = False
            limits.append(f"scanner {scanner_id} produced invalid SARIF: {exc}")
    occurrences: list[Occurrence] = [occ for result in ingested for occ in result.occurrences]
    lens_report: LensLaneReport | None = None
    lens_notes: list[str] = []
    lens_found: list[Occurrence] = []
    if lens_catalog is not None and lens_models:
        try:
            lens_occurrences, lens_report = await run_lens_lane(
                source.path, lens_catalog, lens_models, revision=revision
            )
            occurrences.extend(lens_occurrences)
            lens_found = list(lens_occurrences)
            lens_notes = list(lens_report.notes)
        except LensLaneUnavailableError as exc:
            lens_notes = [str(exc)]
    context = AnalysisContext(
        revision=revision,
        exposure=config.exposure,
        known_exploited=config.known_exploited,
    )
    issues = build_issues(occurrences, catalog, context)
    verifier_results: tuple[VerifierResult, ...] = ()
    if verifier_catalog is not None:
        verifier_results = taint_rule_verifications(
            issues, occurrences, verifier_catalog, repository=source.path
        )
        verifier_results += verify_issues(source.path, issues, verifier_catalog, revision=revision)
    verified = dict(verified_confidence(verifier_results))
    if verified:
        issues = build_issues(occurrences, catalog, replace(context, verifications=verified))
    proof_results: tuple[ProofResult, ...] = ()
    proof_enabled = prove_python is not None or bool(prove_runtimes)
    if proof_enabled:
        proof_results = await prove_issues(
            source.path,
            issues,
            verifier_results,
            sandbox=sandbox,
            python=prove_python,
            runtimes=prove_runtimes,
        )
        proven = proven_confidence(proof_results)
        if proven:
            issues = build_issues(
                occurrences, catalog, replace(context, verifications={**verified, **proven})
            )
    receipt = build_receipt(
        revision,
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
    if prepared_source is not None:
        prepared_source.verify_tree()
    review_source = (
        replace(config.source, revision_kind=source.revision_kind)
        if config.source is not None
        else None
    )
    package = build_review_package(
        issues,
        repository_alias=config.repository_alias,
        revision=revision,
        exposure=config.exposure,
        coverage_complete=complete,
        source=review_source,
        producers=sorted(
            {run.producer for run in receipt.runs} | {o.producer for o in occurrences}
        ),
    )
    (artifacts / "receipt.json").write_text(
        json.dumps(
            {
                "receipt": receipt_to_dict(receipt),
                "coverage_limits": limits,
                "tree_id": source.tree_id,
                **(
                    {"prepared_manifest_digest": prepared_source.manifest_digest}
                    if prepared_source
                    else {}
                ),
                "lens": {
                    "ran": lens_report is not None,
                    "complete": lens_report.complete if lens_report else False,
                    "kept": lens_report.kept if lens_report else 0,
                    "model_calls": lens_report.model_calls if lens_report else 0,
                    "notes": lens_notes,
                    "report": (
                        {key: value for key, value in asdict(lens_report).items() if key != "notes"}
                        if lens_report
                        else None
                    ),
                    "hypotheses": [
                        {
                            "path": occ.location.path,
                            "line": occ.location.start_line,
                            "rule_id": occ.rule_id,
                            "cwe": list(occ.cwe_ids),
                        }
                        for occ in lens_found
                    ],
                },
                "proof": {
                    "enabled": proof_enabled,
                    "results": [item.as_dict() for item in proof_results],
                },
                "verifiers": {
                    "catalog": (
                        f"{verifier_catalog.catalog_id}@{verifier_catalog.version}"
                        if verifier_catalog
                        else None
                    ),
                    "results": [item.as_dict() for item in verifier_results],
                },
            },
            indent=2,
        )
        + "\n"
    )
    (artifacts / "review.json").write_text(json.dumps(package, indent=2) + "\n")
    published = await publisher.publish_code_security_drift(package) if publisher else False
    return ScanJobResult(
        revision=revision,
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
        verifier_results=verifier_results,
        proof_results=proof_results,
        revision_kind=source.revision_kind,
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
