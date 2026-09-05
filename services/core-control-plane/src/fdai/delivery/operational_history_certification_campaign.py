"""Evaluate the dev-only synthetic OI-16 operational-history certification campaign.

The campaign reduces bounded independent observations of deployed synthetic behavior to
one sanitized manifest that :mod:`fdai.delivery.operational_history_certification_cli`
consumes. Evaluation is pure: missing, partial, or conflicting evidence yields
``failed`` or ``unavailable`` and never ``passed``. Deployment wiring lives in
:mod:`fdai.delivery.operational_history_certification_campaign_probes`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioResult,
    OperationalHistoryScenarioStatus,
)
from fdai.core.ontology_platform.operational_history_pressure import StoragePressurePolicy
from fdai.shared.config.models import RuntimeEnv

SYNTHETIC_SCOPE_PREFIX = "synthetic/oi16-certification/"
MANIFEST_SCHEMA_VERSION = "1.0.0"
MERGE_IDENTITY_FIELDS = (
    "schema_version",
    "campaign_id",
    "scope_digest",
    "source_revision_digest",
    "ontology_release_digest",
)
CAMPAIGN_PURPOSE = "operational-history-certification"
MAX_BLAST_RADIUS = 8
MAX_PARTITIONS = 64

DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_SCOPE_SUFFIX = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,63}")
CAMPAIGN_ID_PATTERN = re.compile(r"certify-history-[0-9a-f]{48}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]{8,18}\+00:00")
_REVISION = re.compile(r"[0-9a-zA-Z][0-9a-zA-Z._-]{0,127}")
_UNAVAILABLE_SUFFIX = "_unavailable"
# Only concrete transport faults may degrade a scenario to unavailable. Broad
# OSError and RuntimeError cover configuration and programming defects, which
# MUST fail the job instead of being reported as missing evidence.
PROBE_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)
_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign")


class CampaignPhase(StrEnum):
    """Split the campaign around an externally executed database restart."""

    SINGLE_PASS = "single_pass"  # noqa: S105 - phase name, not a credential
    PRE_RESTART = "pre_restart"
    POST_RESTART = "post_restart"
    MERGED = "merged"


RUNNABLE_PHASES = (CampaignPhase.SINGLE_PASS, CampaignPhase.PRE_RESTART, CampaignPhase.POST_RESTART)
_RESTART_SCENARIOS = frozenset(
    {OperationalHistoryScenario.DATABASE_RESTART, OperationalHistoryScenario.DATABASE_RECOVERY}
)
_EVALUATION_ORDER = (
    OperationalHistoryScenario.WARM_REPLAY,
    OperationalHistoryScenario.SCHEMA_REPLAY,
    OperationalHistoryScenario.DUPLICATE_DELIVERY,
    OperationalHistoryScenario.LATE_OBSERVATION,
    OperationalHistoryScenario.DELETE_RECREATE,
    OperationalHistoryScenario.PROVIDER_FAILURE,
    OperationalHistoryScenario.HOLD_ENFORCEMENT,
    OperationalHistoryScenario.ARCHIVE_OUTAGE,
    OperationalHistoryScenario.ARCHIVE_RESTORE,
    OperationalHistoryScenario.SAFE_PARTITION_PURGE,
    OperationalHistoryScenario.BOUNDED_STORAGE,
    OperationalHistoryScenario.DATABASE_RESTART,
    OperationalHistoryScenario.DATABASE_RECOVERY,
)

REQUIRED_CHECKS: Mapping[OperationalHistoryScenario, tuple[str, ...]] = {
    OperationalHistoryScenario.BOUNDED_STORAGE: (
        "storage_pressure_bounded",
        "purge_backlog_bounded",
        "projection_lag_bounded",
        "partition_count_bounded",
    ),
    OperationalHistoryScenario.WARM_REPLAY: (
        "checkpoint_present",
        "checkpoint_journal_backed",
        "checkpoint_completeness_not_overclaimed",
        "replay_state_preserved",
        "replay_digest_matches",
        "replay_watermarks_match",
        "replay_graph_digest_matches",
    ),
    OperationalHistoryScenario.ARCHIVE_RESTORE: (
        "manifest_verified",
        "restore_sample_passed",
        "artifact_content_verified",
        "restore_scope_authorized",
    ),
    OperationalHistoryScenario.SAFE_PARTITION_PURGE: (
        "dry_run_succeeded",
        "blast_radius_bounded",
        "logical_target_locked",
        "synthetic_target_only",
        "stop_condition_declared",
        "idempotency_key_stable",
        "two_phase_audit_recorded",
        "rollback_tested",
        "effect_verified",
    ),
    OperationalHistoryScenario.SCHEMA_REPLAY: (
        "current_release_replayed",
        "prior_release_replayed",
        "archived_prior_record_present",
        "cross_release_graph_stable",
    ),
    OperationalHistoryScenario.DATABASE_RECOVERY: (
        "recovery_receipt_complete",
        "database_records_restored",
        "journal_watermark_restored",
        "projection_watermark_restored",
        "archive_index_digest_restored",
    ),
    OperationalHistoryScenario.HOLD_ENFORCEMENT: (
        "active_hold_detected",
        "purge_blocked_by_hold",
        "source_data_preserved",
    ),
    OperationalHistoryScenario.DUPLICATE_DELIVERY: (
        "duplicate_suppressed",
        "state_unchanged_on_replay",
        "idempotency_key_stable",
    ),
    OperationalHistoryScenario.LATE_OBSERVATION: (
        "correction_partition_created",
        "correction_replay_complete",
        "correction_closure_recorded",
    ),
    OperationalHistoryScenario.DELETE_RECREATE: (
        "prior_incarnation_recorded",
        "new_incarnation_distinct",
        "incarnation_history_disjoint",
    ),
    OperationalHistoryScenario.PROVIDER_FAILURE: (
        "failure_isolated",
        "partial_evidence_marked_incomplete",
        "no_false_completeness",
    ),
    OperationalHistoryScenario.DATABASE_RESTART: (
        "restart_receipt_present",
        "warm_state_intact_after_restart",
        "no_evidence_loss_after_restart",
    ),
    OperationalHistoryScenario.ARCHIVE_OUTAGE: (
        "archive_outage_detected",
        "warm_path_unaffected",
        "purge_blocked_during_outage",
    ),
}


@dataclass(frozen=True, slots=True)
class SyntheticScope:
    """Dev-only synthetic observation scope that the campaign may target."""

    environment: str
    scope_ref: str

    def __post_init__(self) -> None:
        if self.environment != RuntimeEnv.DEV:
            raise ValueError("synthetic certification scope requires the dev runtime environment")
        if not self.scope_ref.startswith(SYNTHETIC_SCOPE_PREFIX):
            raise ValueError("certification scope MUST use the synthetic certification prefix")
        suffix = self.scope_ref[len(SYNTHETIC_SCOPE_PREFIX) :]
        if _SCOPE_SUFFIX.fullmatch(suffix) is None:
            raise ValueError("synthetic certification scope suffix is invalid")

    @property
    def digest(self) -> str:
        """Return the sanitized scope identity published in the manifest."""

        return _text_digest(self.scope_ref)

    def owns(self, scope_ref: str) -> bool:
        """Report whether an observed scope belongs to this synthetic partition."""

        return scope_ref == self.scope_ref


@dataclass(frozen=True, slots=True)
class CampaignBinding:
    """Pin one campaign to an exact revision, ontology release, and time window."""

    scope: SyntheticScope
    source_revision: str
    ontology_release_digest: str
    window_start: datetime
    window_end: datetime
    campaign_id_override: str | None = None

    def __post_init__(self) -> None:
        if _REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("campaign source revision MUST be bounded ASCII revision text")
        if DIGEST_PATTERN.fullmatch(self.ontology_release_digest) is None:
            raise ValueError("campaign ontology release digest is invalid")
        override = self.campaign_id_override
        if override is not None and CAMPAIGN_ID_PATTERN.fullmatch(override) is None:
            raise ValueError("campaign id MUST match the protected campaign request pattern")
        for value in (self.window_start, self.window_end):
            if value.tzinfo is None:
                raise ValueError("campaign window timestamps MUST be timezone-aware")
        if self.window_start >= self.window_end:
            raise ValueError("campaign window MUST be a positive interval")

    @property
    def campaign_id(self) -> str:
        """Return the stable protected campaign request id for this binding."""

        if self.campaign_id_override is not None:
            return self.campaign_id_override
        material = "|".join(
            (
                self.scope.scope_ref,
                self.source_revision,
                self.ontology_release_digest,
                self.window_start.astimezone(UTC).isoformat(),
                self.window_end.astimezone(UTC).isoformat(),
            )
        )
        return "certify-history-" + hashlib.sha256(material.encode()).hexdigest()[:48]

    def idempotency_key(self, scenario: OperationalHistoryScenario, *, target: str = "") -> str:
        """Return a stable per-scenario, per-target idempotency key."""

        material = "|".join((self.campaign_id, scenario.value, target))
        return "oi16-" + hashlib.sha256(material.encode()).hexdigest()[:48]


@dataclass(frozen=True, slots=True)
class ScenarioCheck:
    """One named bounded check whose truth is known, false, or unobserved."""

    code: str
    satisfied: bool | None

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.code) is None:
            raise ValueError("certification check code MUST be a bounded snake_case token")


@dataclass(frozen=True, slots=True)
class ScenarioObservation:
    """Bounded independent evidence observed for one certification scenario."""

    scenario: OperationalHistoryScenario
    checks: tuple[ScenarioCheck, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        codes = tuple(item.code for item in self.checks)
        if len(set(codes)) != len(codes):
            raise ValueError("certification scenario checks MUST be unique")
        for digest in self.evidence_digests:
            if DIGEST_PATTERN.fullmatch(digest) is None:
                raise ValueError("certification evidence digest is invalid")
        reason = self.unavailable_reason
        if reason is not None and (
            _TOKEN.fullmatch(reason) is None or not reason.endswith(_UNAVAILABLE_SUFFIX)
        ):
            raise ValueError("unavailable reason MUST be a snake_case _unavailable token")


@dataclass(frozen=True, slots=True)
class RecoveryBaseline:
    """Independent warm-state watermarks captured around a database restart."""

    journal_watermark: int
    projection_watermark: int
    archive_index_digest: str
    partition_count: int

    def __post_init__(self) -> None:
        if DIGEST_PATTERN.fullmatch(self.archive_index_digest) is None:
            raise ValueError("recovery baseline archive index digest is invalid")
        if min(self.journal_watermark, self.projection_watermark, self.partition_count) < 0:
            raise ValueError("recovery baseline counters MUST NOT be negative")


class OperationalHistoryCampaignProbes(Protocol):
    """Supply bounded independent evidence for each OI-16 scenario."""

    async def observe(
        self,
        scenario: OperationalHistoryScenario,
        binding: CampaignBinding,
        *,
        now: datetime,
    ) -> ScenarioObservation | None: ...

    async def baseline(
        self, binding: CampaignBinding, *, now: datetime
    ) -> RecoveryBaseline | None: ...


def evaluate_scenario(
    scenario: OperationalHistoryScenario,
    observation: ScenarioObservation | None,
) -> OperationalHistoryScenarioResult:
    """Reduce one observation to a scenario result without ever inferring a pass."""

    if observation is None:
        return _result(scenario, (), ("scenario_evidence_unavailable",))
    if observation.scenario is not scenario:
        return _result(scenario, (), ("scenario_binding_mismatch",))
    if observation.unavailable_reason is not None:
        return _result(scenario, (), (observation.unavailable_reason,))
    observed = {item.code: item.satisfied for item in observation.checks}
    codes = list(REQUIRED_CHECKS[scenario])
    codes.extend(code for code in observed if code not in codes)
    reasons: set[str] = set()
    for code in codes:
        satisfied = observed.get(code)
        if satisfied is None:
            reasons.add(f"{code}{_UNAVAILABLE_SUFFIX}")
        elif not satisfied:
            reasons.add(code)
    digests = tuple(sorted(set(observation.evidence_digests)))
    if not digests:
        reasons.add(f"evidence_digests{_UNAVAILABLE_SUFFIX}")
    return _result(scenario, digests, tuple(sorted(reasons)))


def _result(
    scenario: OperationalHistoryScenario,
    digests: tuple[str, ...],
    reasons: tuple[str, ...],
) -> OperationalHistoryScenarioResult:
    if not reasons:
        return OperationalHistoryScenarioResult(
            scenario=scenario,
            status=OperationalHistoryScenarioStatus.PASSED,
            evidence_digests=digests,
        )
    status = (
        OperationalHistoryScenarioStatus.UNAVAILABLE
        if all(reason.endswith(_UNAVAILABLE_SUFFIX) for reason in reasons)
        else OperationalHistoryScenarioStatus.FAILED
    )
    return OperationalHistoryScenarioResult(
        scenario=scenario,
        status=status,
        evidence_digests=digests,
        reason_codes=reasons,
    )


class OperationalHistoryCertificationCampaign:
    """Evaluate every OI-16 scenario for one phase and emit a sanitized manifest."""

    def __init__(
        self,
        *,
        probes: OperationalHistoryCampaignProbes,
        binding: CampaignBinding,
        phase: CampaignPhase = CampaignPhase.SINGLE_PASS,
    ) -> None:
        if phase not in RUNNABLE_PHASES:
            raise ValueError("campaign phase MUST be runnable")
        self._probes = probes
        self._binding = binding
        self._phase = phase

    async def run(self, *, now: datetime) -> dict[str, object]:
        """Observe every in-phase scenario and return one sanitized manifest."""

        if now.tzinfo is None:
            raise ValueError("campaign recorded_at MUST be timezone-aware")
        results: list[OperationalHistoryScenarioResult] = []
        for scenario in _EVALUATION_ORDER:
            skip = self._skip_reason(scenario)
            if skip is not None:
                results.append(_result(scenario, (), (skip,)))
                continue
            results.append(evaluate_scenario(scenario, await self._observe(scenario, now)))
        return campaign_manifest(self._binding, tuple(results), phase=self._phase, now=now)

    async def _observe(
        self, scenario: OperationalHistoryScenario, now: datetime
    ) -> ScenarioObservation | None:
        try:
            return await self._probes.observe(scenario, self._binding, now=now)
        except PROBE_TRANSPORT_ERRORS:
            _LOGGER.warning("campaign probe failed closed", extra={"scenario": scenario.value})
            return None

    def _skip_reason(self, scenario: OperationalHistoryScenario) -> str | None:
        restart = scenario in _RESTART_SCENARIOS
        if self._phase is CampaignPhase.PRE_RESTART and restart:
            return "restart_phase_pending_unavailable"
        if self._phase is CampaignPhase.POST_RESTART and not restart:
            return "prior_phase_evidence_unavailable"
        return None


def campaign_manifest(
    binding: CampaignBinding,
    results: Sequence[OperationalHistoryScenarioResult],
    *,
    phase: CampaignPhase,
    now: datetime,
) -> dict[str, object]:
    """Build the sanitized manifest consumed by the certification CLI."""

    scenarios = {
        result.scenario.value: {
            "status": result.status.value,
            "evidence_digests": list(result.evidence_digests),
            "reason_codes": list(result.reason_codes),
        }
        for result in sorted(results, key=lambda item: item.scenario.value)
    }
    manifest: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "campaign_id": binding.campaign_id,
        "phase": phase.value,
        "scope_digest": binding.scope.digest,
        "source_revision_digest": _text_digest(binding.source_revision),
        "ontology_release_digest": binding.ontology_release_digest,
        "window_start": _instant(binding.window_start),
        "window_end": _instant(binding.window_end),
        "recorded_at": _instant(now),
        "deterministic_complete": all(
            entry["status"] == OperationalHistoryScenarioStatus.PASSED.value
            for entry in scenarios.values()
        ),
        "scenarios": scenarios,
    }
    assert_sanitized(manifest)
    return manifest


def merge_campaign_phases(
    prior: Mapping[str, object], current: Mapping[str, object]
) -> dict[str, object]:
    """Merge two phases, downgrading any conflicting scenario evidence to failed."""

    _assert_shared_identity(prior, current)
    prior_scenarios = _scenarios_of(prior)
    current_scenarios = _scenarios_of(current)
    merged: dict[str, dict[str, object]] = {}
    for scenario in sorted(set(prior_scenarios) | set(current_scenarios)):
        merged[scenario] = _merge_entry(
            prior_scenarios.get(scenario), current_scenarios.get(scenario)
        )
    manifest = dict(current)
    manifest["phase"] = CampaignPhase.MERGED.value
    manifest["scenarios"] = merged
    manifest["recorded_at"] = max(str(prior["recorded_at"]), str(current["recorded_at"]))
    manifest["window_start"] = min(str(prior["window_start"]), str(current["window_start"]))
    manifest["window_end"] = max(str(prior["window_end"]), str(current["window_end"]))
    manifest["deterministic_complete"] = all(
        entry["status"] == OperationalHistoryScenarioStatus.PASSED.value
        for entry in merged.values()
    )
    assert_sanitized(manifest)
    return manifest


def _assert_shared_identity(prior: Mapping[str, object], current: Mapping[str, object]) -> None:
    """Reject any merge that would splice evidence across two campaign identities.

    A shared campaign id alone never authorizes a merge: the two phases MUST also
    agree on the manifest schema, the synthetic scope, the source revision, and the
    ontology release, and every one of those fields MUST be present as a non-empty
    string on both sides so that an absent field cannot compare equal to itself.
    """

    for field in MERGE_IDENTITY_FIELDS:
        prior_value = prior.get(field)
        current_value = current.get(field)
        if not isinstance(prior_value, str) or not isinstance(current_value, str):
            raise ValueError(f"campaign phases MUST both declare {field}")
        if not prior_value or prior_value != current_value:
            raise ValueError(f"campaign phases MUST share one {field}")


def _merge_entry(
    prior: Mapping[str, object] | None, current: Mapping[str, object] | None
) -> dict[str, object]:
    if prior is None and current is None:
        return _entry(
            OperationalHistoryScenarioStatus.UNAVAILABLE, (), ("phase_evidence_unavailable",)
        )
    if _is_unavailable(prior):
        return dict(current if current is not None else prior or {})
    if _is_unavailable(current) or prior == current:
        return dict(prior if prior is not None else current or {})
    resolved_prior = prior if prior is not None else {}
    resolved_current = current if current is not None else {}
    digests = _union(resolved_prior, resolved_current, "evidence_digests")
    reasons = _union(
        resolved_prior, resolved_current, "reason_codes", extra="phase_evidence_conflict"
    )
    return _entry(OperationalHistoryScenarioStatus.FAILED, digests, reasons)


def _union(
    prior: Mapping[str, object],
    current: Mapping[str, object],
    key: str,
    *,
    extra: str | None = None,
) -> tuple[str, ...]:
    values = set(_strings(prior, key) + _strings(current, key))
    if extra is not None:
        values.add(extra)
    return tuple(sorted(values))


def _entry(
    status: OperationalHistoryScenarioStatus,
    digests: tuple[str, ...],
    reasons: tuple[str, ...],
) -> dict[str, object]:
    return {
        "status": status.value,
        "evidence_digests": list(digests),
        "reason_codes": list(reasons),
    }


def _is_unavailable(entry: Mapping[str, object] | None) -> bool:
    return (
        entry is None or entry.get("status") == OperationalHistoryScenarioStatus.UNAVAILABLE.value
    )


def _scenarios_of(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw = manifest.get("scenarios")
    if not isinstance(raw, Mapping):
        raise ValueError("campaign manifest scenarios MUST be an object")
    return {str(key): cast(Mapping[str, object], value) for key, value in raw.items()}


def _strings(entry: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = entry.get(key, [])
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError("campaign manifest evidence lists MUST be arrays")
    return tuple(str(item) for item in raw)


def assert_sanitized(value: object, *, path: str = "manifest") -> None:
    """Fail closed when any manifest value could carry tenant or resource text."""

    if isinstance(value, bool) or value is None or isinstance(value, int):
        return
    if isinstance(value, str):
        if not _is_safe_text(value):
            raise ValueError(f"campaign manifest value at {path} is not sanitized")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _TOKEN.fullmatch(key) is None:
                raise ValueError(f"campaign manifest key at {path} is not sanitized")
            assert_sanitized(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence):
        for index, item in enumerate(value):
            assert_sanitized(item, path=f"{path}[{index}]")
        return
    raise ValueError(f"campaign manifest value at {path} has an unsupported type")


def _is_safe_text(value: str) -> bool:
    return (
        any(
            pattern.fullmatch(value) is not None
            for pattern in (DIGEST_PATTERN, _TOKEN, CAMPAIGN_ID_PATTERN, _TIMESTAMP)
        )
        or value == MANIFEST_SCHEMA_VERSION
    )


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def evidence_digest(payload: Mapping[str, object]) -> str:
    """Return a canonical content digest for one bounded evidence body."""

    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def scenario_check(code: str, satisfied: bool | None) -> ScenarioCheck:
    return ScenarioCheck(code=code, satisfied=satisfied)


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """Write one sanitized manifest privately for the protected workflow."""

    assert_sanitized(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def read_manifest(path: Path) -> dict[str, object]:
    """Read one previously written campaign phase manifest."""

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("campaign phase manifest MUST be an object")
    return cast(dict[str, object], loaded)


def binding_from_env(
    environ: Mapping[str, str],
    *,
    source_revision: str,
    ontology_release_digest: str,
    window_seconds: int,
    now: datetime,
    campaign_id: str | None = None,
) -> CampaignBinding:
    """Build the campaign binding from the dev-only synthetic scope contract.

    No N-1 ontology release is bound here. Schema replay is a claim about record
    payloads, so it replays a persisted current record and its archived N-1 form
    through the shared provider contract rather than comparing release labels.
    """

    scope = SyntheticScope(
        environment=environ.get("FDAI_ENV", "").strip(),
        scope_ref=environ.get("FDAI_OPERATIONAL_HISTORY_SYNTHETIC_SCOPE", "").strip(),
    )
    if window_seconds < 1:
        raise ValueError("campaign window seconds MUST be positive")
    return CampaignBinding(
        scope=scope,
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        window_start=now - timedelta(seconds=window_seconds),
        window_end=now,
        campaign_id_override=campaign_id,
    )


def policy_from_env(environ: Mapping[str, str]) -> StoragePressurePolicy:
    """Build the bounded storage-pressure policy from the runtime environment."""

    return StoragePressurePolicy(
        warning_bytes=_bounded(environ, "FDAI_OPERATIONAL_HISTORY_WARNING_BYTES", 10 * 1024**3),
        critical_bytes=_bounded(environ, "FDAI_OPERATIONAL_HISTORY_CRITICAL_BYTES", 20 * 1024**3),
        hard_bytes=_bounded(environ, "FDAI_OPERATIONAL_HISTORY_HARD_BYTES", 30 * 1024**3),
        max_purge_backlog=_bounded(environ, "FDAI_OPERATIONAL_HISTORY_MAX_PURGE_BACKLOG", 256),
        max_projection_lag=_bounded(environ, "FDAI_OPERATIONAL_HISTORY_MAX_PROJECTION_LAG", 1000),
    )


def _bounded(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, "").strip()
    return default if not raw else int(raw)


def baseline_from_manifest(manifest: Mapping[str, object] | None) -> RecoveryBaseline | None:
    """Recover the pre-restart baseline recorded by an earlier campaign phase."""

    raw = None if manifest is None else manifest.get("recovery_baseline")
    if not isinstance(raw, Mapping):
        return None
    return RecoveryBaseline(
        journal_watermark=int(cast(int, raw["journal_watermark"])),
        projection_watermark=int(cast(int, raw["projection_watermark"])),
        archive_index_digest=str(raw["archive_index_digest"]),
        partition_count=int(cast(int, raw["partition_count"])),
    )


__all__ = [
    "CAMPAIGN_ID_PATTERN",
    "CAMPAIGN_PURPOSE",
    "DIGEST_PATTERN",
    "MANIFEST_SCHEMA_VERSION",
    "MERGE_IDENTITY_FIELDS",
    "MAX_BLAST_RADIUS",
    "MAX_PARTITIONS",
    "PROBE_TRANSPORT_ERRORS",
    "REQUIRED_CHECKS",
    "RUNNABLE_PHASES",
    "SYNTHETIC_SCOPE_PREFIX",
    "CampaignBinding",
    "CampaignPhase",
    "OperationalHistoryCampaignProbes",
    "OperationalHistoryCertificationCampaign",
    "RecoveryBaseline",
    "ScenarioCheck",
    "ScenarioObservation",
    "SyntheticScope",
    "assert_sanitized",
    "baseline_from_manifest",
    "binding_from_env",
    "campaign_manifest",
    "evaluate_scenario",
    "evidence_digest",
    "merge_campaign_phases",
    "policy_from_env",
    "read_manifest",
    "scenario_check",
    "write_manifest",
]


if __name__ == "__main__":  # pragma: no cover - protected job entry point
    from fdai.delivery.operational_history_certification_campaign_cli import main

    raise SystemExit(main())
