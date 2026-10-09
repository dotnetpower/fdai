"""Rebuild a prepared review from controller-owned observations before durable recording.

Callers supply observations captured outside the scanner-writable artifact directory. Neither a
review file nor a scanner's receipt is a substitute for these observations. Remote adapters still
need an authenticated observation transport; this module does not create remote attestations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from fdai.core.security.code_findings.issue_summary import summarize_issues
from fdai.delivery.code_security_prepared_source import PreparedSource
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, ScannerRunResult
from fdai.delivery.code_security_scan_job import ScanJobConfig, ScanJobResult, run_scan_job
from fdai.delivery.code_security_scan_requests import ScanOutcome
from fdai.delivery.persistence.state_store_code_security_review import record_code_security_review
from fdai.rule_catalog.code_security import CodeSecurityCatalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog, ScannerSpec
from fdai.rule_catalog.code_security_verifiers import VerifierCatalog
from fdai.shared.providers.state_store import StateStore


class ScanResultRejectedError(ValueError):
    """Observed source, scanner execution, or rebuilt findings differ from the candidate."""


class ObservedScanSandbox(BubblewrapScannerSandbox):
    """Keep immutable process observations in controller memory, outside artifact storage."""

    def __init__(self, bwrap: Path) -> None:
        super().__init__(bwrap)
        self._runs: list[ScannerRunResult] = []

    @property
    def observations(self) -> tuple[ScannerRunResult, ...]:
        return tuple(self._runs)

    async def run(
        self,
        scanner_id: str,
        spec: ScannerSpec,
        executable: Path,
        source: Path,
        *,
        rules: Path | None = None,
        cache: Path | None = None,
        environ: Mapping[str, str] | None = None,
        limit_address_space: bool = True,
        system_config: Sequence[Path] = (),
    ) -> ScannerRunResult:
        observed = await super().run(
            scanner_id,
            spec,
            executable,
            source,
            rules=rules,
            cache=cache,
            environ=environ,
            limit_address_space=limit_address_space,
            system_config=system_config,
        )
        self._runs.append(observed)
        return observed


class _ObservationReplay(BubblewrapScannerSandbox):
    def __init__(self, observations: Sequence[ScannerRunResult], scanners: ScannerCatalog) -> None:
        self._observations: dict[str, ScannerRunResult] = {}
        for run in observations:
            spec = scanners.scanners.get(run.scanner_id)
            if spec is None or run.scanner_id in self._observations:
                raise ScanResultRejectedError("unknown or duplicate scanner observation")
            if run.producer != spec.producer:
                raise ScanResultRejectedError("scanner observation producer does not match")
            completed = (
                run.exit_code in spec.success_exit_codes and not run.truncated and not run.timed_out
            )
            if run.completed != completed or len(run.stdout) > spec.max_output_bytes:
                raise ScanResultRejectedError("scanner completion observation is inconsistent")
            self._observations[run.scanner_id] = run
        self.consumed: set[str] = set()

    async def run(
        self,
        scanner_id: str,
        spec: ScannerSpec,
        executable: Path,
        source: Path,
        *,
        rules: Path | None = None,
        cache: Path | None = None,
        environ: Mapping[str, str] | None = None,
        limit_address_space: bool = True,
        system_config: Sequence[Path] = (),
    ) -> ScannerRunResult:
        if scanner_id not in self._observations:
            raise ScanResultRejectedError("bound scanner has no independent observation")
        self.consumed.add(scanner_id)
        return self._observations[scanner_id]

    def require_consumed(self) -> None:
        if self.consumed != set(self._observations):
            raise ScanResultRejectedError("unbound scanner observation cannot be accepted")


async def accept_prepared_scan(
    candidate: ScanJobResult,
    *,
    prepared: PreparedSource,
    observations: Sequence[ScannerRunResult],
    config: ScanJobConfig,
    catalog: CodeSecurityCatalog,
    scanners: ScannerCatalog,
    verifier_catalog: VerifierCatalog | None,
    verification_work_root: Path,
) -> ScanOutcome:
    """Recompute findings using trusted bindings and captured stdout, never candidate files.

    This deterministic acceptance path does not support model or dynamic-proof promotion.
    Those lanes need their own independently observed evidence before cross-process acceptance.
    """
    if (
        candidate.revision != prepared.acquired.revision
        or candidate.tree_id != prepared.acquired.tree_id
        or candidate.revision_kind != prepared.acquired.revision_kind
        or candidate.lens_report is not None
        or candidate.proof_results
        or candidate.published
    ):
        raise ScanResultRejectedError("candidate identity or evidence lane is not supported")
    if verification_work_root.resolve().is_relative_to(prepared.acquired.path.resolve()):
        raise ScanResultRejectedError("verification output must be outside source")
    if config.required_scanners and config.required_scanners - set(scanners.scanners):
        raise ScanResultRejectedError("required scanner is not registered")
    replay = _ObservationReplay(observations, scanners)
    rebuilt = await run_scan_job(
        replace(config, work_root=verification_work_root),
        catalog=catalog,
        scanners=scanners,
        acquirer=None,
        sandbox=replay,
        prepared_source=prepared,
        verifier_catalog=verifier_catalog,
    )
    replay.require_consumed()
    if (
        candidate.package != rebuilt.package
        or candidate.issues != rebuilt.issues
        or candidate.receipt != rebuilt.receipt
        or candidate.coverage_limits != rebuilt.coverage_limits
    ):
        raise ScanResultRejectedError("candidate differs from independently rebuilt findings")
    summaries, truncated = summarize_issues(rebuilt.issues)
    return ScanOutcome(rebuilt.package, summaries, truncated)


async def record_accepted_prepared_scan(
    store: StateStore,
    candidate: ScanJobResult,
    *,
    prepared: PreparedSource,
    observations: Sequence[ScannerRunResult],
    config: ScanJobConfig,
    catalog: CodeSecurityCatalog,
    scanners: ScannerCatalog,
    verifier_catalog: VerifierCatalog | None,
    verification_work_root: Path,
) -> bool:
    """Record only an independently rebuilt result; rejection performs no state-store writes."""
    outcome = await accept_prepared_scan(
        candidate,
        prepared=prepared,
        observations=observations,
        config=config,
        catalog=catalog,
        scanners=scanners,
        verifier_catalog=verifier_catalog,
        verification_work_root=verification_work_root,
    )
    return await record_code_security_review(
        store, outcome.package, issues=outcome.issues, issues_truncated=outcome.issues_truncated
    )
