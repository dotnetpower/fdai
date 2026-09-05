"""Protected job CLI and after-restart finalization for the OI-16 campaign.

This module owns the stable Container Apps Job entry point for
:mod:`fdai.delivery.operational_history_certification_campaign` and the optional
``--finalize`` contract that lets the *same* job process turn merged restart
evidence into a persisted certification receipt.

Finalizing in-process keeps the database DSN, the archive container URL, the
merged manifest, and the receipt inside the job. The runner only observes the
sanitized summary printed on stdout: booleans, reason codes, digests, the
campaign id, and the protected campaign run id. Nothing tenant-shaped or
resource-shaped ever leaves the job.

Order of operations for ``--finalize`` (after-restart only):

1. Run the after-restart phase and merge it with the persisted before-restart
   phase evidence.
2. Write the merged sanitized manifest to ``--output``.
3. Refuse missing, failed, unavailable, release-conflicted, or structurally invalid
   certification evidence before invoking any durable finalization sink.
4. Persist the same merged manifest through
   :class:`~fdai.delivery.operational_history_certification_campaign_phase_store.CampaignPhaseStore`
   under :data:`CampaignPhase.MERGED`, so the private Blob artifact outlives the job
   container.
5. Only then invoke the existing
   certification CLI ``run()`` to build, persist, and privately write the
   receipt.

Missing, unavailable, failed, or unmerged evidence returns a refused summary and
exit ``1`` without ever invoking certification persistence or writing the receipt
output. A missing or malformed protected binding raises and exits ``2``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import psycopg

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryProtectedBinding,
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
    AzureBlobOperationalHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.operational_history_archive import OperationalArchiveArtifact
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_ID_PATTERN,
    MANIFEST_SCHEMA_VERSION,
    CampaignPhase,
    assert_sanitized,
    binding_from_env,
    write_manifest,
)
from fdai.delivery.operational_history_certification_campaign_phase_store import CampaignPhaseStore
from fdai.delivery.operational_history_certification_campaign_release import (
    PROJECTION_UNAVAILABLE,
    RELEASE_VERIFIED,
    ProjectionStateReader,
    ReleaseResolution,
    projected_release_digest,
    projection_state,
    release_blockers,
    resolved_release,
)
from fdai.delivery.operational_history_certification_cli import (
    build_certification_from_manifest,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)

MAX_BINDING_VALUE_CHARS = 128
PHASE_ALIASES: Mapping[str, CampaignPhase] = {
    "single-pass": CampaignPhase.SINGLE_PASS,
    "before-restart": CampaignPhase.PRE_RESTART,
    "after-restart": CampaignPhase.POST_RESTART,
}
BINDING_ENV: Mapping[str, tuple[str, ...]] = {
    "required_ci_run_id": ("FDAI_REQUIRED_CI_RUN_ID",),
    "runtime_image_revision": ("FDAI_RUNTIME_IMAGE_REVISION", "APPLY_RUNTIME_IMAGE_REVISION"),
    "runtime_image_digest": ("FDAI_RUNTIME_IMAGE_DIGEST",),
    "runtime_attestation_digest": ("FDAI_RUNTIME_ATTESTATION_DIGEST",),
    "deployment_revision": ("FDAI_DEPLOYMENT_REVISION", "DEPLOYMENT_REVISION"),
    "deployment_apply_run_id": ("FDAI_DEPLOYMENT_APPLY_RUN_ID", "DEPLOYMENT_APPLY_RUN_ID"),
    "deployment_receipt_digest": ("FDAI_DEPLOYMENT_RECEIPT_DIGEST", "DEPLOYMENT_RECEIPT_DIGEST"),
    "campaign_run_id": ("GITHUB_RUN_ID", "FDAI_CAMPAIGN_RUN_ID"),
}
_RUN_ID_FIELDS = frozenset({"required_ci_run_id", "deployment_apply_run_id", "campaign_run_id"})
_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign.cli")


@dataclass(frozen=True, slots=True)
class CampaignRunOptions:
    """Bounded, fully resolved options for one campaign phase run."""

    phase: CampaignPhase
    output: Path
    source_revision: str
    ontology_release_digest: str
    campaign_id: str | None = None
    prior_phase: Path | None = None
    restart_receipt_digest: str | None = None
    window_seconds: int = 3600
    prepare_fixture: bool = True
    finalize: bool = False
    receipt_output: Path | None = None
    release_assertion: str = RELEASE_VERIFIED
    """How ``ontology_release_digest`` was established. See the release module."""


class MergedPhaseSink(Protocol):
    """Scope-bound sink for the merged campaign phase artifact."""

    async def put(
        self,
        manifest: Mapping[str, object],
        *,
        campaign_id: str,
        phase: CampaignPhase,
        now: datetime,
    ) -> OperationalArchiveArtifact: ...


class CertificationRunner(Protocol):
    """The existing certification CLI ``run()`` contract."""

    async def __call__(
        self,
        *,
        evidence_path: Path,
        output_path: Path,
        source_revision: str,
        ontology_release_digest: str,
        dsn: str,
        deployment_receipt_digest: str | None = None,
        protected_binding: OperationalHistoryProtectedBinding | None = None,
    ) -> dict[str, object]: ...


def build_parser() -> argparse.ArgumentParser:
    """Return the stable protected job CLI for the certification campaign."""

    parser = argparse.ArgumentParser(
        prog="python -m fdai.delivery.operational_history_certification_campaign",
        description="Run one dev-only synthetic OI-16 certification campaign phase.",
    )
    parser.add_argument("--phase", default="single-pass", choices=tuple(PHASE_ALIASES))
    parser.add_argument("--campaign-id", help="Protected campaign request id shared by phases.")
    parser.add_argument("--output", required=True, type=Path, help="Sanitized manifest path.")
    parser.add_argument("--source-revision", help="Defaults to FDAI_SOURCE_REVISION.")
    parser.add_argument(
        "--ontology-release-digest",
        help=(
            "Assert the expected catalog release. The campaign always binds the "
            "source-built catalog release; a mismatch refuses certification."
        ),
    )
    parser.add_argument("--prior-phase", type=Path, help="Override the persisted phase artifact.")
    parser.add_argument("--restart-receipt-digest")
    parser.add_argument("--window-seconds", type=int, default=3600)
    parser.add_argument("--skip-fixture", action="store_true")
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="After-restart only: persist merged evidence and certify in this job.",
    )
    parser.add_argument("--receipt-output", type=Path, help="Private receipt path for --finalize.")
    return parser


def options_from_args(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    *,
    release: ReleaseResolution | None = None,
) -> CampaignRunOptions:
    """Resolve CLI arguments and environment defaults into bounded run options.

    The ontology release digest is never taken from the caller. It is rebuilt from
    the shipped ontology catalog, exactly as the inventory synchronization job
    builds the release the checkpoint repository records, because that identity is
    what schema replay compares against. A caller-supplied digest is retained only
    as an assertion whose disagreement refuses a protected certification claim.
    """

    revision = args.source_revision or environ.get("FDAI_SOURCE_REVISION", "").strip()
    if not revision:
        raise ValueError("campaign requires a source revision")
    asserted = (
        args.ontology_release_digest or environ.get("FDAI_ONTOLOGY_RELEASE_DIGEST", "").strip()
    )
    resolution = resolved_release(asserted) if release is None else release
    campaign_id = args.campaign_id or environ.get("FDAI_CAMPAIGN_ID", "").strip() or None
    if campaign_id is not None and CAMPAIGN_ID_PATTERN.fullmatch(campaign_id) is None:
        raise ValueError("campaign id MUST match the protected campaign request pattern")
    phase = PHASE_ALIASES[str(args.phase)]
    finalize = bool(args.finalize)
    if finalize != (args.receipt_output is not None):
        raise ValueError("campaign finalization requires exactly one receipt output path")
    if finalize and phase is not CampaignPhase.POST_RESTART:
        raise ValueError("campaign finalization is an after-restart-only contract")
    if finalize and campaign_id is None:
        raise ValueError("campaign finalization requires an explicit campaign id")
    return CampaignRunOptions(
        phase=phase,
        output=Path(args.output),
        source_revision=revision,
        ontology_release_digest=resolution.digest,
        campaign_id=campaign_id,
        prior_phase=None if args.prior_phase is None else Path(args.prior_phase),
        restart_receipt_digest=args.restart_receipt_digest,
        window_seconds=int(args.window_seconds),
        prepare_fixture=not bool(args.skip_fixture),
        finalize=finalize,
        receipt_output=None if args.receipt_output is None else Path(args.receipt_output),
        release_assertion=resolution.assertion,
    )


def phase_exit_code(manifest: Mapping[str, object], phase: CampaignPhase) -> int:
    """Return ``0`` only when the phase produced acceptable evidence."""

    if phase is not CampaignPhase.PRE_RESTART:
        return 0 if manifest.get("deterministic_complete") is True else 1
    failed = OperationalHistoryScenarioStatus.FAILED.value
    entries = _scenarios(manifest).values()
    return 1 if any(e.get("status") == failed for e in entries) else 0


def finalize_blockers(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Return every sorted reason that blocks a protected certification claim."""

    reasons: set[str] = set()
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        reasons.add("manifest_schema_unsupported")
    if manifest.get("phase") != CampaignPhase.MERGED.value:
        reasons.add("restart_phases_not_merged")
    if manifest.get("deterministic_complete") is not True:
        reasons.add("evidence_not_deterministic_complete")
    scenarios = _scenarios(manifest)
    for scenario in OperationalHistoryScenario:
        entry = scenarios.get(scenario.value)
        if entry is None:
            reasons.add("scenario_evidence_missing")
            continue
        status = entry.get("status")
        if status == OperationalHistoryScenarioStatus.UNAVAILABLE.value:
            reasons.add("scenario_evidence_unavailable")
        elif status != OperationalHistoryScenarioStatus.PASSED.value:
            reasons.add("scenario_evidence_failed")
        digests = entry.get("evidence_digests")
        if not isinstance(digests, Sequence) or not digests:
            reasons.add("scenario_evidence_digests_missing")
    return tuple(sorted(reasons))


def protected_binding_from_env(
    environ: Mapping[str, str], *, source_revision: str, campaign_id: str
) -> OperationalHistoryProtectedBinding:
    """Resolve the protected workflow binding from bounded job environment values."""

    return OperationalHistoryProtectedBinding(
        source_revision=source_revision,
        required_ci_run_id=_binding_run_id(environ, "required_ci_run_id"),
        runtime_image_revision=_binding_text(environ, "runtime_image_revision"),
        runtime_image_digest=_binding_text(environ, "runtime_image_digest"),
        runtime_attestation_digest=_binding_text(environ, "runtime_attestation_digest"),
        deployment_revision=_binding_text(environ, "deployment_revision"),
        deployment_apply_run_id=_binding_run_id(environ, "deployment_apply_run_id"),
        deployment_receipt_digest=_binding_text(environ, "deployment_receipt_digest"),
        campaign_run_id=_binding_run_id(environ, "campaign_run_id"),
        campaign_request_id=campaign_id,
    )


async def finalize_campaign(
    manifest: Mapping[str, object],
    options: CampaignRunOptions,
    environ: Mapping[str, str],
    *,
    now: datetime | None = None,
    sink: MergedPhaseSink | None = None,
    certify: CertificationRunner | None = None,
    projection: ProjectionStateReader | None = None,
) -> dict[str, object]:
    """Persist merged evidence and certify it in-process, or refuse fail-closed.

    Preservation of the final private merged artifact is conditional on every scenario
    passing. A blocked finalization MUST NOT reach the merged sink, the certifier, or
    the receipt output, so refused evidence never leaves a durable artifact that could
    later be mistaken for a certified campaign. Per-phase evidence written before the
    restart is untouched, because restart continuity depends on it.

    The receipt may only bind a release identity this runtime actually established.
    An unverifiable or refuted catalog release, or a persisted projection record that
    contradicts it, blocks certification the same way missing scenario evidence does.
    """

    moment = datetime.now(UTC) if now is None else now.astimezone(UTC)
    if options.phase is not CampaignPhase.POST_RESTART:
        raise ValueError("campaign finalization is an after-restart-only contract")
    if options.receipt_output is None:
        raise ValueError("campaign finalization requires a private receipt output path")
    campaign_id = options.campaign_id
    if campaign_id is None:
        raise ValueError("campaign finalization requires an explicit campaign id")
    if manifest.get("campaign_id") != campaign_id:
        raise ValueError("merged campaign evidence does not match the requested campaign id")
    assert_sanitized(manifest)
    binding = protected_binding_from_env(
        environ, source_revision=options.source_revision, campaign_id=campaign_id
    )
    projected = await _projection_state(options, environ, reader=projection)
    blockers = tuple(
        sorted(
            set(finalize_blockers(manifest))
            | set(release_blockers(options.release_assertion, projected))
        )
    )
    if blockers:
        _LOGGER.error("campaign finalization refused incomplete merged evidence")
        return _summary(campaign_id, binding, None, reason_codes=blockers)
    candidate = build_certification_from_manifest(
        manifest,
        source_revision=options.source_revision,
        ontology_release_digest=options.ontology_release_digest,
        deployment_receipt_digest=binding.deployment_receipt_digest,
        protected_binding=binding,
    )
    if not candidate.operationally_validated:
        raise ValueError("campaign finalization candidate is not operationally validated")
    artifact_digest = await _persist_merged(
        manifest, options=options, environ=environ, campaign_id=campaign_id, now=moment, sink=sink
    )
    runner = _certification_runner() if certify is None else certify
    summary = await runner(
        evidence_path=options.output,
        output_path=options.receipt_output,
        source_revision=options.source_revision,
        ontology_release_digest=options.ontology_release_digest,
        dsn=_dsn(environ),
        deployment_receipt_digest=binding.deployment_receipt_digest,
        protected_binding=binding,
    )
    validated = summary.get("operationally_validated") is True
    persisted = summary.get("persisted") is True
    reasons: tuple[str, ...] = ()
    if not validated:
        reasons += ("certification_not_operationally_validated",)
    if not persisted:
        reasons += ("certification_receipt_not_persisted",)
    return _summary(
        campaign_id,
        binding,
        artifact_digest,
        reason_codes=tuple(sorted(reasons)),
        receipt_digest=_digest_or_none(summary.get("receipt_digest")),
        operationally_validated=validated,
        persisted=persisted,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one campaign phase, persist its evidence, and write its manifest."""

    args = build_parser().parse_args(argv)
    logging.basicConfig(level=os.environ.get("FDAI_LOG_LEVEL", "INFO"))
    try:
        options = options_from_args(args, os.environ)
        from fdai.delivery.operational_history_certification_campaign_runner import run_phase

        manifest = asyncio.run(run_phase(options, os.environ))
        assert_sanitized(manifest)
        write_manifest(options.output, manifest)
        if options.finalize:
            summary = asyncio.run(finalize_campaign(manifest, options, os.environ))
            print(json.dumps(summary, sort_keys=True))
            return 0 if summary["finalized"] is True else 1
    except Exception:
        _LOGGER.exception("operational history certification campaign failed closed")
        return 2
    return phase_exit_code(manifest, options.phase)


async def _projection_state(
    options: CampaignRunOptions,
    environ: Mapping[str, str],
    *,
    reader: ProjectionStateReader | None = None,
) -> str:
    """Compare the deployed projection release with the release being bound.

    A database that cannot be read, or that carries no projection record, grades
    as unavailable rather than as agreement, so absence never certifies anything.
    """

    store = (
        PostgresStateStore(config=PostgresStateStoreConfig(dsn=_dsn(environ)))
        if reader is None
        else reader
    )
    try:
        projected = await projected_release_digest(store)
    except (psycopg.Error, ConnectionError, TimeoutError):
        _LOGGER.warning("campaign could not read the persisted ontology projection record")
        return PROJECTION_UNAVAILABLE
    return projection_state(options.ontology_release_digest, projected)


async def _persist_merged(
    manifest: Mapping[str, object],
    *,
    options: CampaignRunOptions,
    environ: Mapping[str, str],
    campaign_id: str,
    now: datetime,
    sink: MergedPhaseSink | None,
) -> str:
    """Store the merged manifest so the private artifact survives the job."""

    if sink is not None:
        artifact = await sink.put(
            manifest, campaign_id=campaign_id, phase=CampaignPhase.MERGED, now=now
        )
        return artifact.artifact_digest
    container_url = environ.get("FDAI_OPERATIONAL_HISTORY_CONTAINER_URL", "").strip()
    if not container_url:
        raise ValueError("campaign finalization requires an archive container URL")
    scope = binding_from_env(
        environ,
        source_revision=options.source_revision,
        ontology_release_digest=options.ontology_release_digest,
        window_seconds=options.window_seconds,
        now=now,
        campaign_id=campaign_id,
    ).scope
    history = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(dsn=_dsn(environ))
    )
    async with httpx.AsyncClient() as http_client:
        artifacts = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(container_url=container_url),
            identity=ManagedIdentityWorkloadIdentity.from_env(
                http_client=http_client, client_id_env="FDAI_MI_CLIENT_ID"
            ),
            http_client=http_client,
        )
        store = CampaignPhaseStore(artifacts=artifacts, metadata=history, scope=scope)
        artifact = await store.put(
            manifest, campaign_id=campaign_id, phase=CampaignPhase.MERGED, now=now
        )
    return artifact.artifact_digest


def _certification_runner() -> CertificationRunner:
    from fdai.delivery.operational_history_certification_cli import run

    return run


def _summary(
    campaign_id: str,
    binding: OperationalHistoryProtectedBinding,
    merged_artifact_digest: str | None,
    *,
    reason_codes: tuple[str, ...],
    receipt_digest: str | None = None,
    operationally_validated: bool = False,
    persisted: bool = False,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "campaign_id": campaign_id,
        "campaign_run_id": binding.campaign_run_id,
        "finalized": not reason_codes and operationally_validated and persisted,
        "merged_artifact_digest": merged_artifact_digest,
        "operationally_validated": operationally_validated,
        "persisted": persisted,
        "phase": CampaignPhase.MERGED.value,
        "reason_codes": list(reason_codes),
        "receipt_digest": receipt_digest,
    }
    assert_sanitized(summary)
    return summary


def _scenarios(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = manifest.get("scenarios")
    if not isinstance(raw, Mapping):
        raise ValueError("campaign manifest scenarios MUST be an object")
    entries: dict[str, Mapping[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, Mapping):
            raise ValueError("campaign manifest scenario evidence MUST be an object")
        entries[str(key)] = value
    return entries


def _binding_text(environ: Mapping[str, str], field: str) -> str:
    names = BINDING_ENV[field]
    for name in names:
        value = environ.get(name, "").strip()
        if not value:
            continue
        if len(value) > MAX_BINDING_VALUE_CHARS:
            raise ValueError(f"protected certification binding value {name} is out of bound")
        return value
    raise ValueError(f"protected certification binding is missing {names[0]}")


def _binding_run_id(environ: Mapping[str, str], field: str) -> int:
    value = _binding_text(environ, field)
    if not value.isdigit():
        raise ValueError(f"protected certification binding {field} MUST be a positive integer")
    return int(value)


def _digest_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _dsn(environ: Mapping[str, str]) -> str:
    dsn = environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        raise ValueError("campaign finalization requires a database URL")
    return dsn


__all__ = [
    "BINDING_ENV",
    "MAX_BINDING_VALUE_CHARS",
    "PHASE_ALIASES",
    "CampaignRunOptions",
    "CertificationRunner",
    "MergedPhaseSink",
    "build_parser",
    "finalize_blockers",
    "finalize_campaign",
    "main",
    "options_from_args",
    "phase_exit_code",
    "protected_binding_from_env",
]


if __name__ == "__main__":  # pragma: no cover - alternate module entry point
    raise SystemExit(main())
