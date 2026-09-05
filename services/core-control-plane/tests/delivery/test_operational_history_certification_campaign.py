"""Deterministic tests for the dev-only synthetic OI-16 certification campaign."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.ontology_platform.archive_manifest import ArchiveManifest, ArchiveVerificationReceipt
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.delivery.operational_history_archive import OperationalArchiveArtifact
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_PURPOSE,
    MAX_PARTITIONS,
    MERGE_IDENTITY_FIELDS,
    PROBE_TRANSPORT_ERRORS,
    REQUIRED_CHECKS,
    CampaignBinding,
    CampaignPhase,
    OperationalHistoryCertificationCampaign,
    RecoveryBaseline,
    ScenarioCheck,
    ScenarioObservation,
    SyntheticScope,
    assert_sanitized,
    baseline_from_manifest,
    binding_from_env,
    evaluate_scenario,
    evidence_digest,
    merge_campaign_phases,
    policy_from_env,
    read_manifest,
    scenario_check,
    write_manifest,
)
from fdai.delivery.operational_history_certification_campaign_cli import (
    PHASE_ALIASES,
    build_parser,
    main,
    options_from_args,
    phase_exit_code,
)
from fdai.delivery.operational_history_certification_campaign_phase_store import (
    CampaignPhaseStore,
    phase_key_digest,
    phase_storage_ref,
)
from fdai.delivery.operational_history_certification_campaign_release import (
    resolve_release_digest,
)
from fdai.delivery.operational_history_certification_cli import (
    build_certification_from_manifest,
)

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
SOURCE = "376dc306765e6a182542f2818e14c9b73d0d1a38"
SCOPE_REF = "synthetic/oi16-certification/dev-fixture"
ENVIRON = {"FDAI_ENV": "dev", "FDAI_OPERATIONAL_HISTORY_SYNTHETIC_SCOPE": SCOPE_REF}


def _binding() -> CampaignBinding:
    return CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref=SCOPE_REF),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
    )


class _FakeProbes:
    """Return prepared observations without touching any deployed adapter."""

    def __init__(
        self,
        observations: Mapping[OperationalHistoryScenario, ScenarioObservation | None],
        *,
        baseline: RecoveryBaseline | None = None,
        raise_for: OperationalHistoryScenario | None = None,
        error: Exception | None = None,
    ) -> None:
        self._observations = dict(observations)
        self._baseline = baseline
        self._raise_for = raise_for
        self._error = error or ConnectionError("probe transport failed")
        self.observed: list[OperationalHistoryScenario] = []

    async def observe(
        self,
        scenario: OperationalHistoryScenario,
        binding: CampaignBinding,
        *,
        now: datetime,
    ) -> ScenarioObservation | None:
        self.observed.append(scenario)
        if scenario is self._raise_for:
            raise self._error
        return self._observations.get(scenario)

    async def baseline(self, binding: CampaignBinding, *, now: datetime) -> RecoveryBaseline | None:
        return self._baseline


def _passing(scenario: OperationalHistoryScenario) -> ScenarioObservation:
    return ScenarioObservation(
        scenario=scenario,
        checks=tuple(scenario_check(code, True) for code in REQUIRED_CHECKS[scenario]),
        evidence_digests=(EVIDENCE,),
    )


def _all_passing() -> dict[OperationalHistoryScenario, ScenarioObservation]:
    return {scenario: _passing(scenario) for scenario in OperationalHistoryScenario}


def test_non_synthetic_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="synthetic certification prefix"):
        SyntheticScope(environment="dev", scope_ref="subscriptions/prod/resourceGroups/rg-live")


def test_non_dev_environment_is_rejected() -> None:
    with pytest.raises(ValueError, match="dev runtime environment"):
        SyntheticScope(environment="prod", scope_ref=SCOPE_REF)


def test_binding_from_env_rejects_a_missing_synthetic_scope() -> None:
    with pytest.raises(ValueError, match="synthetic certification prefix"):
        binding_from_env(
            {"FDAI_ENV": "dev", "FDAI_OPERATIONAL_HISTORY_SYNTHETIC_SCOPE": ""},
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            window_seconds=3600,
            now=NOW,
        )


def test_campaign_id_and_idempotency_keys_are_stable_and_protected_shaped() -> None:
    binding = _binding()
    other = CampaignBinding(
        scope=binding.scope,
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=binding.window_start,
        window_end=binding.window_end + timedelta(seconds=1),
    )
    assert binding.campaign_id == _binding().campaign_id
    assert binding.campaign_id != other.campaign_id
    assert binding.campaign_id.startswith("certify-history-")
    assert len(binding.campaign_id) == len("certify-history-") + 48
    scenario = OperationalHistoryScenario.SAFE_PARTITION_PURGE
    assert binding.idempotency_key(scenario, target=EVIDENCE) == binding.idempotency_key(
        scenario, target=EVIDENCE
    )
    assert binding.idempotency_key(scenario, target=EVIDENCE) != binding.idempotency_key(
        scenario, target=RELEASE
    )


def test_missing_observation_is_unavailable_not_passed() -> None:
    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, None)
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == ("scenario_evidence_unavailable",)
    assert result.evidence_digests == ()


def test_unobserved_check_never_becomes_a_pass() -> None:
    scenario = OperationalHistoryScenario.SAFE_PARTITION_PURGE
    checks = tuple(
        scenario_check(code, None if code == "effect_verified" else True)
        for code in REQUIRED_CHECKS[scenario]
    )
    result = evaluate_scenario(
        scenario,
        ScenarioObservation(scenario=scenario, checks=checks, evidence_digests=(EVIDENCE,)),
    )
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == ("effect_verified_unavailable",)


def test_failed_check_dominates_an_unavailable_check() -> None:
    scenario = OperationalHistoryScenario.SAFE_PARTITION_PURGE
    checks = tuple(
        scenario_check(code, {"effect_verified": None, "rollback_tested": False}.get(code, True))
        for code in REQUIRED_CHECKS[scenario]
    )
    result = evaluate_scenario(
        scenario,
        ScenarioObservation(scenario=scenario, checks=checks, evidence_digests=(EVIDENCE,)),
    )
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert result.reason_codes == ("effect_verified_unavailable", "rollback_tested")


def test_missing_required_check_is_unavailable() -> None:
    scenario = OperationalHistoryScenario.HOLD_ENFORCEMENT
    result = evaluate_scenario(
        scenario,
        ScenarioObservation(
            scenario=scenario,
            checks=(scenario_check("active_hold_detected", True),),
            evidence_digests=(EVIDENCE,),
        ),
    )
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == (
        "purge_blocked_by_hold_unavailable",
        "source_data_preserved_unavailable",
    )


def test_evidence_free_observation_never_passes() -> None:
    scenario = OperationalHistoryScenario.BOUNDED_STORAGE
    result = evaluate_scenario(
        scenario,
        ScenarioObservation(
            scenario=scenario,
            checks=tuple(scenario_check(code, True) for code in REQUIRED_CHECKS[scenario]),
        ),
    )
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == ("evidence_digests_unavailable",)


def test_scenario_binding_mismatch_fails_closed() -> None:
    result = evaluate_scenario(
        OperationalHistoryScenario.WARM_REPLAY,
        _passing(OperationalHistoryScenario.ARCHIVE_RESTORE),
    )
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert result.reason_codes == ("scenario_binding_mismatch",)


def test_observation_rejects_unsanitized_reason_and_digest() -> None:
    with pytest.raises(ValueError, match="_unavailable token"):
        ScenarioObservation(
            scenario=OperationalHistoryScenario.WARM_REPLAY,
            unavailable_reason="scope /subscriptions/live missing",
        )
    with pytest.raises(ValueError, match="evidence digest is invalid"):
        ScenarioObservation(
            scenario=OperationalHistoryScenario.WARM_REPLAY,
            evidence_digests=("rg-production-eastus",),
        )
    with pytest.raises(ValueError, match="snake_case token"):
        ScenarioCheck(code="Resource Group Check", satisfied=True)


async def test_complete_campaign_is_deterministically_complete_and_sanitized() -> None:
    binding = _binding()
    campaign = OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding
    )
    manifest = await campaign.run(now=NOW)
    assert manifest["deterministic_complete"] is True
    assert manifest["campaign_id"] == binding.campaign_id
    assert manifest["phase"] == CampaignPhase.SINGLE_PASS.value
    assert SCOPE_REF not in json.dumps(manifest)
    assert SOURCE not in json.dumps(manifest)
    receipt = build_certification_from_manifest(
        manifest,
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
    )
    assert receipt.deterministic_complete is True
    assert receipt.operationally_validated is False


async def test_probe_transport_failure_is_reported_as_unavailable() -> None:
    campaign = OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing(), raise_for=OperationalHistoryScenario.ARCHIVE_OUTAGE),
        binding=_binding(),
    )
    manifest = await campaign.run(now=NOW)
    scenarios = manifest["scenarios"]
    assert isinstance(scenarios, dict)
    entry = scenarios[OperationalHistoryScenario.ARCHIVE_OUTAGE.value]
    assert entry["status"] == OperationalHistoryScenarioStatus.UNAVAILABLE.value
    assert manifest["deterministic_complete"] is False


async def test_probe_programming_defect_is_never_downgraded_to_unavailable() -> None:
    campaign = OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(
            _all_passing(),
            raise_for=OperationalHistoryScenario.ARCHIVE_OUTAGE,
            error=AttributeError("campaign probe defect"),
        ),
        binding=_binding(),
    )
    with pytest.raises(AttributeError, match="campaign probe defect"):
        await campaign.run(now=NOW)
    assert not isinstance(AttributeError(), PROBE_TRANSPORT_ERRORS)


async def test_pre_restart_phase_defers_restart_scenarios() -> None:
    probes = _FakeProbes(_all_passing())
    campaign = OperationalHistoryCertificationCampaign(
        probes=probes, binding=_binding(), phase=CampaignPhase.PRE_RESTART
    )
    manifest = await campaign.run(now=NOW)
    scenarios = manifest["scenarios"]
    assert isinstance(scenarios, dict)
    for scenario in (
        OperationalHistoryScenario.DATABASE_RESTART,
        OperationalHistoryScenario.DATABASE_RECOVERY,
    ):
        assert scenario not in probes.observed
        entry = scenarios[scenario.value]
        assert entry["status"] == OperationalHistoryScenarioStatus.UNAVAILABLE.value
        assert entry["reason_codes"] == ["restart_phase_pending_unavailable"]
    assert manifest["deterministic_complete"] is False


async def test_post_restart_phase_only_observes_restart_scenarios() -> None:
    probes = _FakeProbes(_all_passing())
    campaign = OperationalHistoryCertificationCampaign(
        probes=probes, binding=_binding(), phase=CampaignPhase.POST_RESTART
    )
    await campaign.run(now=NOW)
    assert set(probes.observed) == {
        OperationalHistoryScenario.DATABASE_RESTART,
        OperationalHistoryScenario.DATABASE_RECOVERY,
    }


async def test_merged_phases_complete_only_when_both_phases_pass() -> None:
    binding = _binding()
    pre = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding, phase=CampaignPhase.PRE_RESTART
    ).run(now=NOW)
    post = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding, phase=CampaignPhase.POST_RESTART
    ).run(now=NOW + timedelta(minutes=5))
    merged = merge_campaign_phases(pre, post)
    assert merged["phase"] == CampaignPhase.MERGED.value
    assert merged["deterministic_complete"] is True
    receipt = build_certification_from_manifest(
        merged, source_revision=SOURCE, ontology_release_digest=RELEASE
    )
    assert receipt.deterministic_complete is True


async def test_conflicting_phase_evidence_downgrades_to_failed() -> None:
    binding = _binding()
    pre = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding
    ).run(now=NOW)
    conflicting = {
        scenario: ScenarioObservation(
            scenario=scenario,
            checks=tuple(scenario_check(code, True) for code in REQUIRED_CHECKS[scenario]),
            evidence_digests=(RELEASE,),
        )
        for scenario in OperationalHistoryScenario
    }
    post = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(conflicting), binding=binding
    ).run(now=NOW + timedelta(minutes=5))
    merged = merge_campaign_phases(pre, post)
    scenarios = merged["scenarios"]
    assert isinstance(scenarios, dict)
    entry = scenarios[OperationalHistoryScenario.WARM_REPLAY.value]
    assert entry["status"] == OperationalHistoryScenarioStatus.FAILED.value
    assert "phase_evidence_conflict" in entry["reason_codes"]
    assert merged["deterministic_complete"] is False


async def test_merge_rejects_a_foreign_campaign() -> None:
    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    foreign = dict(first)
    foreign["campaign_id"] = "certify-history-" + "0" * 48
    with pytest.raises(ValueError, match="share one campaign_id"):
        merge_campaign_phases(first, foreign)


async def test_merge_rejects_evidence_from_a_foreign_scope_source_or_release() -> None:
    """A shared campaign id MUST NOT splice evidence across two campaign identities."""

    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    foreign_binding = CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref="synthetic/oi16-certification/other"),
        source_revision="c0ffee0000000000000000000000000000000001",
        ontology_release_digest="sha256:" + "b" * 64,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
        campaign_id_override=str(first["campaign_id"]),
    )
    second = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=foreign_binding
    ).run(now=NOW + timedelta(minutes=5))
    assert second["campaign_id"] == first["campaign_id"]
    for field in ("scope_digest", "source_revision_digest", "ontology_release_digest"):
        assert first[field] != second[field]
    with pytest.raises(ValueError, match="MUST share one"):
        merge_campaign_phases(first, second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0.0"),
        ("campaign_id", "certify-history-" + "0" * 48),
        ("scope_digest", "sha256:" + "c" * 64),
        ("source_revision_digest", "sha256:" + "d" * 64),
        ("ontology_release_digest", "sha256:" + "e" * 64),
    ],
)
async def test_merge_rejects_any_mismatched_identity_field(field: str, value: str) -> None:
    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    assert first[field] != value
    second = dict(first)
    second[field] = value
    with pytest.raises(ValueError, match=f"MUST share one {field}"):
        merge_campaign_phases(first, second)
    with pytest.raises(ValueError, match=f"MUST share one {field}"):
        merge_campaign_phases(second, first)


@pytest.mark.parametrize("field", MERGE_IDENTITY_FIELDS)
async def test_merge_rejects_an_absent_identity_field(field: str) -> None:
    """An absent field MUST fail closed rather than compare equal to its own absence."""

    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    one_sided = {key: item for key, item in first.items() if key != field}
    with pytest.raises(ValueError, match=f"MUST both declare {field}"):
        merge_campaign_phases(first, one_sided)
    with pytest.raises(ValueError, match=f"MUST both declare {field}"):
        merge_campaign_phases(one_sided, first)
    with pytest.raises(ValueError, match=f"MUST both declare {field}"):
        merge_campaign_phases(one_sided, dict(one_sided))


@pytest.mark.parametrize("field", MERGE_IDENTITY_FIELDS)
async def test_merge_rejects_a_blank_or_non_text_identity_field(field: str) -> None:
    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    blank = dict(first)
    blank[field] = ""
    with pytest.raises(ValueError, match=f"MUST share one {field}"):
        merge_campaign_phases(blank, dict(blank))
    non_text = dict(first)
    non_text[field] = None
    with pytest.raises(ValueError, match=f"MUST both declare {field}"):
        merge_campaign_phases(first, non_text)


async def test_merge_accepts_two_phases_of_one_identity() -> None:
    binding = _binding()
    first = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding, phase=CampaignPhase.PRE_RESTART
    ).run(now=NOW)
    second = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding, phase=CampaignPhase.POST_RESTART
    ).run(now=NOW + timedelta(minutes=5))
    merged = merge_campaign_phases(first, second)
    for field in MERGE_IDENTITY_FIELDS:
        assert merged[field] == first[field]


def test_sanitizer_rejects_tenant_and_resource_text() -> None:
    with pytest.raises(ValueError, match="not sanitized"):
        assert_sanitized({"scope": "/subscriptions/0000/resourceGroups/rg-live"})
    with pytest.raises(ValueError, match="not sanitized"):
        assert_sanitized({"scenarios": {"warm_replay": {"status": "PASSED"}}})
    with pytest.raises(ValueError, match="key at manifest is not sanitized"):
        assert_sanitized({"Resource-Group": "passed"})
    assert_sanitized(
        {
            "schema_version": "1.0.0",
            "campaign_id": "certify-history-" + "1" * 48,
            "scope_digest": EVIDENCE,
            "recorded_at": NOW.isoformat(),
            "deterministic_complete": False,
            "scenarios": {"warm_replay": {"status": "passed", "evidence_digests": [EVIDENCE]}},
        }
    )


async def test_manifest_round_trip_is_private_and_reloadable(tmp_path: Path) -> None:
    manifest = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    path = tmp_path / "phase" / "manifest.json"
    write_manifest(path, manifest)
    assert path.stat().st_mode & 0o077 == 0
    assert read_manifest(path) == manifest


def test_recovery_baseline_round_trip_and_validation() -> None:
    baseline = RecoveryBaseline(
        journal_watermark=42,
        projection_watermark=42,
        archive_index_digest=EVIDENCE,
        partition_count=3,
    )
    manifest = {
        "recovery_baseline": {
            "journal_watermark": baseline.journal_watermark,
            "projection_watermark": baseline.projection_watermark,
            "archive_index_digest": baseline.archive_index_digest,
            "partition_count": baseline.partition_count,
        }
    }
    assert baseline_from_manifest(manifest) == baseline
    assert baseline_from_manifest({}) is None
    assert baseline_from_manifest(None) is None
    with pytest.raises(ValueError, match="archive index digest is invalid"):
        RecoveryBaseline(
            journal_watermark=1,
            projection_watermark=1,
            archive_index_digest="rg-live",
            partition_count=1,
        )


def test_policy_from_env_uses_bounded_defaults() -> None:
    policy = policy_from_env({"FDAI_OPERATIONAL_HISTORY_MAX_PURGE_BACKLOG": "12"})
    assert policy.max_purge_backlog == 12
    assert policy.max_projection_lag == 1000


def test_evidence_digest_is_canonical_and_order_independent() -> None:
    assert evidence_digest({"a": 1, "b": 2}) == evidence_digest({"b": 2, "a": 1})
    assert evidence_digest({"a": 1}) != evidence_digest({"a": 2})
    assert evidence_digest({"a": 1}).startswith("sha256:")


def test_required_checks_cover_every_scenario() -> None:
    assert set(REQUIRED_CHECKS) == set(OperationalHistoryScenario)
    assert all(checks for checks in REQUIRED_CHECKS.values())
    assert MAX_PARTITIONS > 0


def test_binding_from_env_builds_a_bounded_window() -> None:
    binding = binding_from_env(
        ENVIRON,
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_seconds=600,
        now=NOW,
    )
    assert binding.window_end == NOW
    assert binding.window_start == NOW - timedelta(seconds=600)
    assert binding.scope.scope_ref == SCOPE_REF
    with pytest.raises(ValueError, match="window seconds MUST be positive"):
        binding_from_env(
            ENVIRON,
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            window_seconds=0,
            now=NOW,
        )


# --- protected job CLI + phase persistence -------------------------------------------------


class _FakeArtifacts:
    """In-memory stand-in for the principal-scoped Blob artifact store."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("artifact digest mismatch")
        inserted = storage_ref not in self.blobs
        self.blobs[storage_ref] = content
        return inserted

    async def get(self, storage_ref: str) -> bytes | None:
        return self.blobs.get(storage_ref)


class _FakeManifests:
    def __init__(self) -> None:
        self.rows: dict[str, ArchiveManifest] = {}
        self.verifications: list[ArchiveVerificationReceipt] = []

    async def put_manifest(self, manifest: ArchiveManifest) -> bool:
        inserted = manifest.digest not in self.rows
        self.rows[manifest.digest] = manifest
        return inserted

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        self.verifications.append(receipt)
        return True


class _FakeMetadata:
    def __init__(self) -> None:
        self.rows: dict[str, OperationalArchiveArtifact] = {}

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        inserted = artifact.storage_ref not in self.rows
        self.rows[artifact.storage_ref] = artifact
        return inserted

    async def get_archive_artifact_by_storage_ref(
        self, storage_ref: str
    ) -> OperationalArchiveArtifact | None:
        return self.rows.get(storage_ref)


def _phase_store(
    artifacts: _FakeArtifacts,
    manifests: _FakeManifests,
    metadata: _FakeMetadata,
    *,
    scope_ref: str = SCOPE_REF,
) -> CampaignPhaseStore:
    return CampaignPhaseStore(
        artifacts=artifacts,
        manifests=manifests,
        metadata=metadata,
        scope=SyntheticScope(environment="dev", scope_ref=scope_ref),
    )


CAMPAIGN_ID = "certify-history-" + "7" * 48


def test_phase_refs_are_deterministic_and_carry_no_resource_identifiers() -> None:
    ref = phase_storage_ref(CAMPAIGN_ID, CampaignPhase.PRE_RESTART)
    assert ref == phase_storage_ref(CAMPAIGN_ID, CampaignPhase.PRE_RESTART)
    assert ref.startswith("operational-history/")
    assert CAMPAIGN_ID in ref and SCOPE_REF not in ref
    assert ref != phase_storage_ref(CAMPAIGN_ID, CampaignPhase.POST_RESTART)
    key = phase_key_digest(CAMPAIGN_ID, CampaignPhase.PRE_RESTART)
    assert key.startswith("sha256:")
    assert key != phase_key_digest(CAMPAIGN_ID, CampaignPhase.POST_RESTART)


async def test_phase_artifact_round_trips_through_the_synthetic_scope() -> None:
    manifest = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=_binding()
    ).run(now=NOW)
    artifacts, manifests, metadata = _FakeArtifacts(), _FakeManifests(), _FakeMetadata()
    store = _phase_store(artifacts, manifests, metadata)
    artifact = await store.put(
        manifest, campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART, now=NOW
    )
    assert artifact.scope_refs == (SCOPE_REF,)
    assert artifact.allowed_purposes == (CAMPAIGN_PURPOSE,)
    assert manifests.verifications[-1].verified is True
    assert await store.get(campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART) == manifest
    assert await store.get(campaign_id=CAMPAIGN_ID, phase=CampaignPhase.POST_RESTART) is None


async def test_phase_artifact_bound_to_another_scope_is_denied() -> None:
    artifacts, manifests, metadata = _FakeArtifacts(), _FakeManifests(), _FakeMetadata()
    await _phase_store(artifacts, manifests, metadata, scope_ref=SCOPE_REF + "-other").put(
        {"schema_version": "1.0.0", "ontology_release_digest": RELEASE},
        campaign_id=CAMPAIGN_ID,
        phase=CampaignPhase.PRE_RESTART,
        now=NOW,
    )
    with pytest.raises(PermissionError, match="bound to another scope"):
        await _phase_store(artifacts, manifests, metadata).get(
            campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART
        )


async def test_tampered_phase_artifact_fails_closed() -> None:
    artifacts, manifests, metadata = _FakeArtifacts(), _FakeManifests(), _FakeMetadata()
    store = _phase_store(artifacts, manifests, metadata)
    artifact = await store.put(
        {"schema_version": "1.0.0", "ontology_release_digest": RELEASE},
        campaign_id=CAMPAIGN_ID,
        phase=CampaignPhase.PRE_RESTART,
        now=NOW,
    )
    original = artifacts.blobs[artifact.storage_ref]
    artifacts.blobs[artifact.storage_ref] = original + b" "
    with pytest.raises(ValueError, match="byte count does not match"):
        await store.get(campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART)
    tampered = bytearray(original)
    tampered[-2] = ord(" ")
    artifacts.blobs[artifact.storage_ref] = bytes(tampered)
    with pytest.raises(ValueError, match="content does not match"):
        await store.get(campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART)
    artifacts.blobs.pop(artifact.storage_ref)
    with pytest.raises(LookupError, match="no stored content"):
        await store.get(campaign_id=CAMPAIGN_ID, phase=CampaignPhase.PRE_RESTART)


async def test_unsanitized_phase_manifest_is_never_persisted() -> None:
    artifacts, manifests, metadata = _FakeArtifacts(), _FakeManifests(), _FakeMetadata()
    with pytest.raises(ValueError, match="not sanitized"):
        await _phase_store(artifacts, manifests, metadata).put(
            {"scope": "/subscriptions/0000/resourceGroups/rg-live"},
            campaign_id=CAMPAIGN_ID,
            phase=CampaignPhase.PRE_RESTART,
            now=NOW,
        )
    assert artifacts.blobs == {} and manifests.rows == {} and metadata.rows == {}


def test_cli_accepts_the_protected_job_invocation(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--phase",
            "before-restart",
            "--campaign-id",
            CAMPAIGN_ID,
            "--output",
            str(tmp_path / "before.json"),
        ]
    )
    release = resolve_release_digest(RELEASE, canonical=RELEASE)
    options = options_from_args(
        args,
        {"FDAI_SOURCE_REVISION": SOURCE, "FDAI_ONTOLOGY_RELEASE_DIGEST": RELEASE},
        release=release,
    )
    assert options.phase is CampaignPhase.PRE_RESTART
    assert options.campaign_id == CAMPAIGN_ID
    assert options.source_revision == SOURCE
    assert options.ontology_release_digest == RELEASE
    after = options_from_args(
        build_parser().parse_args(
            ["--phase", "after-restart", "--campaign-id", CAMPAIGN_ID, "--output", "x"]
        ),
        {"FDAI_SOURCE_REVISION": SOURCE, "FDAI_ONTOLOGY_RELEASE_DIGEST": RELEASE},
        release=release,
    )
    assert after.phase is CampaignPhase.POST_RESTART
    assert set(PHASE_ALIASES) == {"single-pass", "before-restart", "after-restart"}


def test_cli_rejects_a_malformed_campaign_id_and_missing_revision() -> None:
    env = {"FDAI_SOURCE_REVISION": SOURCE, "FDAI_ONTOLOGY_RELEASE_DIGEST": RELEASE}
    release = resolve_release_digest(RELEASE, canonical=RELEASE)
    args = build_parser().parse_args(["--campaign-id", "rg-live", "--output", "x"])
    with pytest.raises(ValueError, match="protected campaign request pattern"):
        options_from_args(args, env, release=release)
    with pytest.raises(ValueError, match="campaign requires a source revision"):
        options_from_args(build_parser().parse_args(["--output", "x"]), {}, release=release)


def test_explicit_campaign_id_pins_both_phases_to_one_identity() -> None:
    early = CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref=SCOPE_REF),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
        campaign_id_override=CAMPAIGN_ID,
    )
    late = CampaignBinding(
        scope=early.scope,
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        campaign_id_override=CAMPAIGN_ID,
    )
    assert early.campaign_id == late.campaign_id == CAMPAIGN_ID
    assert _binding().campaign_id != CAMPAIGN_ID
    with pytest.raises(ValueError, match="protected campaign request pattern"):
        CampaignBinding(
            scope=early.scope,
            source_revision=SOURCE,
            ontology_release_digest=RELEASE,
            window_start=NOW - timedelta(hours=1),
            window_end=NOW,
            campaign_id_override="prod-campaign",
        )


async def test_phase_exit_codes_gate_the_protected_workflow() -> None:
    binding = _binding()
    pre = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(_all_passing()), binding=binding, phase=CampaignPhase.PRE_RESTART
    ).run(now=NOW)
    assert phase_exit_code(pre, CampaignPhase.PRE_RESTART) == 0
    assert phase_exit_code(pre, CampaignPhase.POST_RESTART) == 1
    failing = dict(_all_passing())
    scenario = OperationalHistoryScenario.WARM_REPLAY
    failing[scenario] = ScenarioObservation(
        scenario=scenario,
        checks=tuple(scenario_check(code, False) for code in REQUIRED_CHECKS[scenario]),
        evidence_digests=(EVIDENCE,),
    )
    bad = await OperationalHistoryCertificationCampaign(
        probes=_FakeProbes(failing), binding=binding, phase=CampaignPhase.PRE_RESTART
    ).run(now=NOW)
    assert phase_exit_code(bad, CampaignPhase.PRE_RESTART) == 0


def test_main_fails_closed_on_a_non_synthetic_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "manifest.json"
    for key in (
        "FDAI_ENV",
        "FDAI_OPERATIONAL_HISTORY_SYNTHETIC_SCOPE",
        "FDAI_DATABASE_URL",
        "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FDAI_ENV", "prod")
    monkeypatch.setenv("FDAI_OPERATIONAL_HISTORY_SYNTHETIC_SCOPE", "subscriptions/live/rg")
    monkeypatch.setenv("FDAI_SOURCE_REVISION", SOURCE)
    monkeypatch.setenv("FDAI_ONTOLOGY_RELEASE_DIGEST", RELEASE)
    exit_code = main(
        ["--phase", "before-restart", "--campaign-id", CAMPAIGN_ID, "--output", str(output)]
    )
    assert exit_code == 2
    assert not output.exists()


@pytest.mark.parametrize(
    ("scenario", "required"),
    [
        (
            OperationalHistoryScenario.WARM_REPLAY,
            ("checkpoint_journal_backed", "checkpoint_completeness_not_overclaimed"),
        ),
        (
            OperationalHistoryScenario.SCHEMA_REPLAY,
            ("prior_release_replayed", "archived_prior_record_present"),
        ),
    ],
)
def test_replay_scenarios_require_journal_and_projection_evidence(
    scenario: OperationalHistoryScenario, required: tuple[str, ...]
) -> None:
    """A replay probe that omits a required replay precondition MUST NOT pass."""

    for code in required:
        assert code in REQUIRED_CHECKS[scenario]
    legacy = ScenarioObservation(
        scenario=scenario,
        checks=tuple(
            scenario_check(code, True) for code in REQUIRED_CHECKS[scenario] if code not in required
        ),
        evidence_digests=(EVIDENCE,),
    )
    result = evaluate_scenario(scenario, legacy)
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == tuple(sorted(f"{code}_unavailable" for code in required))


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        (OperationalHistoryScenario.WARM_REPLAY, "checkpoint_journal_backed"),
        (OperationalHistoryScenario.WARM_REPLAY, "checkpoint_completeness_not_overclaimed"),
        (OperationalHistoryScenario.WARM_REPLAY, "replay_state_preserved"),
        (OperationalHistoryScenario.SCHEMA_REPLAY, "current_release_replayed"),
        (OperationalHistoryScenario.SCHEMA_REPLAY, "prior_release_replayed"),
        (OperationalHistoryScenario.SCHEMA_REPLAY, "archived_prior_record_present"),
    ],
)
def test_a_defective_replay_precondition_never_certifies_a_replay(
    scenario: OperationalHistoryScenario, code: str
) -> None:
    observation = ScenarioObservation(
        scenario=scenario,
        checks=tuple(scenario_check(item, item != code) for item in REQUIRED_CHECKS[scenario]),
        evidence_digests=(EVIDENCE,),
    )
    result = evaluate_scenario(scenario, observation)
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert result.reason_codes == (code,)
