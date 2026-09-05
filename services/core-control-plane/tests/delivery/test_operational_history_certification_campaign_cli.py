"""Focused tests for the protected after-restart OI-16 finalization contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fdai.core.ontology_platform.archive_manifest import ArchiveManifest, ArchiveVerificationReceipt
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryProtectedBinding,
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.delivery import operational_history_certification_campaign_cli as campaign_cli
from fdai.delivery.operational_history_archive import OperationalArchiveArtifact
from fdai.delivery.operational_history_certification_campaign import (
    CampaignPhase,
    SyntheticScope,
    assert_sanitized,
)
from fdai.delivery.operational_history_certification_campaign_cli import (
    BINDING_ENV,
    CampaignRunOptions,
    build_parser,
    finalize_blockers,
    finalize_campaign,
    options_from_args,
    protected_binding_from_env,
)
from fdai.delivery.operational_history_certification_campaign_phase_store import CampaignPhaseStore
from fdai.delivery.operational_history_certification_campaign_release import (
    PROJECTION_CONFLICTED,
    PROJECTION_MATCHED,
    PROJECTION_UNAVAILABLE,
    RELEASE_CONFLICTED,
    RELEASE_UNVERIFIED,
    RELEASE_VERIFIED,
    canonical_ontology_release_digest,
    projection_state,
    release_blockers,
    resolve_release_digest,
)
from fdai.runtime.inventory_ontology import INVENTORY_ONTOLOGY_MANIFEST_KEY

CAMPAIGN_ID = "certify-history-" + "9" * 48
REVISION = "a" * 40
RELEASE_DIGEST = "sha256:" + "b" * 64
RECEIPT_DIGEST = "sha256:" + "c" * 64
IMAGE_DIGEST = "sha256:" + "d" * 64
ATTESTATION_DIGEST = "sha256:" + "e" * 64
ARTIFACT_DIGEST = "sha256:" + "f" * 64
CATALOG_DIGEST = "sha256:" + "a" * 64
SCOPE_REF = "synthetic/oi16-certification/campaign-a"
NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def _env(**overrides: str) -> dict[str, str]:
    values = {
        "FDAI_ENV": "dev",
        "FDAI_DATABASE_URL": "postgresql://synthetic",
        "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": "https://example.invalid/container",
        "FDAI_REQUIRED_CI_RUN_ID": "4242",
        "FDAI_RUNTIME_IMAGE_REVISION": REVISION,
        "FDAI_RUNTIME_IMAGE_DIGEST": IMAGE_DIGEST,
        "FDAI_RUNTIME_ATTESTATION_DIGEST": ATTESTATION_DIGEST,
        "FDAI_DEPLOYMENT_REVISION": REVISION,
        "FDAI_DEPLOYMENT_APPLY_RUN_ID": "77",
        "FDAI_DEPLOYMENT_RECEIPT_DIGEST": RECEIPT_DIGEST,
        "GITHUB_RUN_ID": "991",
        "FDAI_SOURCE_REVISION": REVISION,
        "FDAI_ONTOLOGY_RELEASE_DIGEST": RELEASE_DIGEST,
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value}


def _options(tmp_path: Path, **overrides: object) -> CampaignRunOptions:
    values: dict[str, object] = {
        "phase": CampaignPhase.POST_RESTART,
        "output": tmp_path / "merged.json",
        "source_revision": REVISION,
        "ontology_release_digest": RELEASE_DIGEST,
        "campaign_id": CAMPAIGN_ID,
        "finalize": True,
        "receipt_output": tmp_path / "receipt.json",
    }
    values.update(overrides)
    return CampaignRunOptions(**values)  # type: ignore[arg-type]


def _manifest(**overrides: object) -> dict[str, object]:
    scenarios: dict[str, object] = {
        scenario.value: {
            "status": OperationalHistoryScenarioStatus.PASSED.value,
            "evidence_digests": ["sha256:" + "1" * 64],
            "reason_codes": [],
        }
        for scenario in OperationalHistoryScenario
    }
    manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "campaign_id": CAMPAIGN_ID,
        "phase": CampaignPhase.MERGED.value,
        "window_start": "2026-03-01T11:00:00+00:00",
        "window_end": "2026-03-01T12:00:00+00:00",
        "recorded_at": "2026-03-01T12:00:00+00:00",
        "source_revision_digest": "sha256:" + hashlib.sha256(REVISION.encode()).hexdigest(),
        "ontology_release_digest": RELEASE_DIGEST,
        "deterministic_complete": True,
        "scenarios": scenarios,
    }
    manifest.update(overrides)
    return manifest


def _scenario_map(manifest: Mapping[str, object]) -> dict[str, object]:
    return dict(cast(Mapping[str, object], manifest["scenarios"]))


def _degrade(status: OperationalHistoryScenarioStatus) -> dict[str, object]:
    manifest = _manifest()
    scenarios = _scenario_map(manifest)
    scenarios[OperationalHistoryScenario.WARM_REPLAY.value] = {
        "status": status.value,
        "evidence_digests": [],
        "reason_codes": ["probe_error_unavailable"],
    }
    manifest["scenarios"] = scenarios
    manifest["deterministic_complete"] = False
    return manifest


class _Artifacts:
    """In-memory stand-in for the principal-scoped Blob artifact store."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        self.blobs[storage_ref] = content
        return True

    async def get(self, storage_ref: str) -> bytes | None:
        return self.blobs.get(storage_ref)


class _Manifests:
    def __init__(self) -> None:
        self.rows: dict[str, ArchiveManifest] = {}
        self.verifications: list[ArchiveVerificationReceipt] = []

    async def put_manifest(self, manifest: ArchiveManifest) -> bool:
        self.rows[manifest.digest] = manifest
        return True

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        self.verifications.append(receipt)
        return True


class _Index:
    def __init__(self) -> None:
        self.rows: dict[str, OperationalArchiveArtifact] = {}

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        self.rows[artifact.storage_ref] = artifact
        return True

    async def get_archive_artifact_by_storage_ref(
        self, storage_ref: str
    ) -> OperationalArchiveArtifact | None:
        return self.rows.get(storage_ref)


class _Sink:
    """The real phase store over in-memory adapters, recording every call."""

    def __init__(self) -> None:
        self.artifacts = _Artifacts()
        self.manifests = _Manifests()
        self.index = _Index()
        self.calls: list[tuple[str, CampaignPhase]] = []
        self._store = CampaignPhaseStore(
            artifacts=self.artifacts,
            manifests=self.manifests,
            metadata=self.index,
            scope=SyntheticScope(environment="dev", scope_ref=SCOPE_REF),
        )

    async def put(
        self,
        manifest: Mapping[str, object],
        *,
        campaign_id: str,
        phase: CampaignPhase,
        now: datetime,
    ) -> OperationalArchiveArtifact:
        self.calls.append((campaign_id, phase))
        return await self._store.put(manifest, campaign_id=campaign_id, phase=phase, now=now)


@dataclass
class _Certifier:
    """Stand in for the existing certification CLI ``run()``."""

    summary: dict[str, object]
    calls: list[Path] = field(default_factory=list)

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
    ) -> dict[str, object]:
        assert protected_binding is not None
        assert protected_binding.campaign_request_id == CAMPAIGN_ID
        self.calls.append(evidence_path)
        output_path.write_text("{}", encoding="utf-8")
        return dict(self.summary)


class _Projection:
    """Bounded read-only stand-in for the persisted ontology projection record."""

    def __init__(self, digest: str | None = RELEASE_DIGEST, *, record: bool = True) -> None:
        self._digest = digest
        self._record = record
        self.keys: list[str] = []

    async def read_state(self, key: str) -> Mapping[str, object] | None:
        self.keys.append(key)
        if not self._record:
            return None
        return {"ontology_release_digest": self._digest} if self._digest else {}


class _UnreadableProjection:
    """A projection record the deployed database cannot be reached to serve."""

    async def read_state(self, key: str) -> Mapping[str, object] | None:
        raise ConnectionError("projection state is unreachable")


def _certified(**overrides: object) -> _Certifier:
    summary: dict[str, object] = {
        "receipt_digest": "sha256:" + "3" * 64,
        "deterministic_complete": True,
        "operationally_validated": True,
        "persisted": True,
    }
    summary.update(overrides)
    return _Certifier(summary=summary)


async def test_complete_evidence_persists_and_certifies_in_process(tmp_path: Path) -> None:
    sink = _Sink()
    certifier = _certified()
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=sink,
        certify=certifier,
        projection=_Projection(),
    )
    assert sink.calls == [(CAMPAIGN_ID, CampaignPhase.MERGED)]
    assert certifier.calls == [tmp_path / "merged.json"]
    assert summary["finalized"] is True
    assert str(summary["merged_artifact_digest"]).startswith("sha256:")
    assert sink.artifacts.blobs
    assert summary["reason_codes"] == []


@pytest.mark.parametrize(
    "status",
    [OperationalHistoryScenarioStatus.UNAVAILABLE, OperationalHistoryScenarioStatus.FAILED],
)
async def test_incomplete_evidence_never_invokes_certification(
    tmp_path: Path, status: OperationalHistoryScenarioStatus
) -> None:
    sink = _Sink()
    certifier = _certified()
    summary = await finalize_campaign(
        _degrade(status),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=sink,
        certify=certifier,
        projection=_Projection(),
    )
    assert certifier.calls == []
    assert not (tmp_path / "receipt.json").exists()
    assert summary["finalized"] is False
    assert summary["operationally_validated"] is False
    assert summary["persisted"] is False
    assert summary["receipt_digest"] is None
    assert sink.calls == []
    assert summary["merged_artifact_digest"] is None


async def test_unmerged_phase_evidence_is_refused(tmp_path: Path) -> None:
    manifest = _manifest(phase=CampaignPhase.POST_RESTART.value)
    certifier = _certified()
    summary = await finalize_campaign(
        manifest,
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=_Sink(),
        certify=certifier,
        projection=_Projection(),
    )
    assert certifier.calls == []
    assert "restart_phases_not_merged" in summary["reason_codes"]  # type: ignore[operator]
    assert summary["finalized"] is False


async def test_certification_without_persistence_is_not_finalized(tmp_path: Path) -> None:
    certifier = _certified(persisted=False)
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=_Sink(),
        certify=certifier,
        projection=_Projection(),
    )
    assert certifier.calls != []
    assert summary["operationally_validated"] is True
    assert summary["persisted"] is False
    assert summary["finalized"] is False
    assert summary["reason_codes"] == ["certification_receipt_not_persisted"]


async def test_unvalidated_certification_is_not_finalized(tmp_path: Path) -> None:
    certifier = _certified(operationally_validated=False)
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=_Sink(),
        certify=certifier,
        projection=_Projection(),
    )
    assert summary["finalized"] is False
    assert "certification_not_operationally_validated" in summary["reason_codes"]  # type: ignore[operator]


@pytest.mark.parametrize("missing", sorted({names[0] for names in BINDING_ENV.values()}))
async def test_missing_binding_value_fails_closed(tmp_path: Path, missing: str) -> None:
    certifier = _certified()
    environ = _env(**{missing: ""})
    environ.pop("APPLY_RUNTIME_IMAGE_REVISION", None)
    with pytest.raises(ValueError, match="protected certification binding"):
        await finalize_campaign(
            _manifest(), _options(tmp_path), environ, now=NOW, sink=_Sink(), certify=certifier
        )
    assert certifier.calls == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FDAI_REQUIRED_CI_RUN_ID", "not-a-number"),
        ("FDAI_REQUIRED_CI_RUN_ID", "0"),
        ("GITHUB_RUN_ID", "-3"),
        ("FDAI_RUNTIME_IMAGE_DIGEST", "not-a-digest"),
        ("FDAI_RUNTIME_IMAGE_REVISION", "z" * 40),
        ("FDAI_DEPLOYMENT_RECEIPT_DIGEST", "sha256:" + "0" * 63),
    ],
)
async def test_malformed_binding_value_fails_closed(tmp_path: Path, name: str, value: str) -> None:
    certifier = _certified()
    with pytest.raises(ValueError):
        await finalize_campaign(
            _manifest(),
            _options(tmp_path),
            _env(**{name: value}),
            now=NOW,
            sink=_Sink(),
            certify=certifier,
        )
    assert certifier.calls == []


async def test_oversized_binding_value_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="out of bound"):
        await finalize_campaign(
            _manifest(),
            _options(tmp_path),
            _env(FDAI_DEPLOYMENT_REVISION="a" * 200),
            now=NOW,
            sink=_Sink(),
            certify=_certified(),
        )


async def test_campaign_id_mismatch_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest(campaign_id="certify-history-" + "8" * 48)
    with pytest.raises(ValueError, match="does not match the requested campaign id"):
        await finalize_campaign(
            manifest, _options(tmp_path), _env(), now=NOW, sink=_Sink(), certify=_certified()
        )


async def test_finalize_is_after_restart_only(tmp_path: Path) -> None:
    options = _options(tmp_path, phase=CampaignPhase.PRE_RESTART)
    with pytest.raises(ValueError, match="after-restart-only"):
        await finalize_campaign(
            _manifest(), options, _env(), now=NOW, sink=_Sink(), certify=_certified()
        )


async def test_finalize_requires_a_receipt_output(tmp_path: Path) -> None:
    options = _options(tmp_path, receipt_output=None)
    with pytest.raises(ValueError, match="receipt output path"):
        await finalize_campaign(
            _manifest(), options, _env(), now=NOW, sink=_Sink(), certify=_certified()
        )


def test_binding_falls_back_to_workflow_native_names() -> None:
    environ = _env(FDAI_DEPLOYMENT_REVISION="", FDAI_RUNTIME_IMAGE_REVISION="")
    environ["DEPLOYMENT_REVISION"] = REVISION
    environ["APPLY_RUNTIME_IMAGE_REVISION"] = REVISION
    binding = protected_binding_from_env(environ, source_revision=REVISION, campaign_id=CAMPAIGN_ID)
    assert binding.deployment_revision == REVISION
    assert binding.campaign_run_id == 991


def test_blockers_flag_missing_scenarios_and_empty_evidence() -> None:
    manifest = _manifest()
    scenarios = _scenario_map(manifest)
    scenarios.pop(OperationalHistoryScenario.DELETE_RECREATE.value)
    scenarios[OperationalHistoryScenario.WARM_REPLAY.value] = {
        "status": OperationalHistoryScenarioStatus.PASSED.value,
        "evidence_digests": [],
        "reason_codes": [],
    }
    manifest["scenarios"] = scenarios
    blockers = finalize_blockers(manifest)
    assert "scenario_evidence_missing" in blockers
    assert "scenario_evidence_digests_missing" in blockers
    assert blockers == tuple(sorted(blockers))


def test_complete_merged_evidence_has_no_blockers() -> None:
    assert finalize_blockers(_manifest()) == ()


def test_cli_rejects_finalize_without_a_receipt_output() -> None:
    args = build_parser().parse_args(
        [
            "--phase",
            "after-restart",
            "--campaign-id",
            CAMPAIGN_ID,
            "--output",
            "m.json",
            "--finalize",
        ]
    )
    with pytest.raises(ValueError, match="exactly one receipt output path"):
        options_from_args(args, _env())


def test_cli_rejects_finalize_before_restart() -> None:
    args = build_parser().parse_args(
        [
            "--phase",
            "before-restart",
            "--campaign-id",
            CAMPAIGN_ID,
            "--output",
            "m.json",
            "--finalize",
            "--receipt-output",
            "r.json",
        ]
    )
    with pytest.raises(ValueError, match="after-restart-only"):
        options_from_args(args, _env())


def test_cli_rejects_a_receipt_output_without_finalize() -> None:
    args = build_parser().parse_args(
        ["--phase", "after-restart", "--output", "m.json", "--receipt-output", "r.json"]
    )
    with pytest.raises(ValueError, match="exactly one receipt output path"):
        options_from_args(args, _env())


def test_cli_resolves_the_finalize_contract() -> None:
    args = build_parser().parse_args(
        [
            "--phase",
            "after-restart",
            "--campaign-id",
            CAMPAIGN_ID,
            "--output",
            "m.json",
            "--finalize",
            "--receipt-output",
            "r.json",
        ]
    )
    options = options_from_args(args, _env())
    assert options.finalize is True
    assert options.receipt_output == Path("r.json")
    assert options.phase is CampaignPhase.POST_RESTART


def test_container_entrypoint_translates_positional_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    merged = str(tmp_path / "merged.json")
    receipt = str(tmp_path / "receipt.json")

    def capture(argv: list[str]) -> int:
        captured.extend(argv)
        return 7

    monkeypatch.setattr(campaign_cli, "main", capture)
    result = campaign_cli.container_main(
        [
            "after-restart",
            CAMPAIGN_ID,
            merged,
            REVISION,
            RECEIPT_DIGEST,
            "true",
            receipt,
        ]
    )

    assert result == 7
    assert captured == [
        "--phase",
        "after-restart",
        "--campaign-id",
        CAMPAIGN_ID,
        "--output",
        merged,
        "--source-revision",
        REVISION,
        "--restart-receipt-digest",
        RECEIPT_DIGEST,
        "--finalize",
        "--receipt-output",
        receipt,
    ]


async def test_summary_is_sanitized_and_carries_no_paths(tmp_path: Path) -> None:
    summary = await finalize_campaign(
        _manifest(), _options(tmp_path), _env(), now=NOW, sink=_Sink(), certify=_certified()
    )
    assert_sanitized(summary)
    rendered = json.dumps(summary, sort_keys=True)
    assert str(tmp_path) not in rendered
    assert "postgresql" not in rendered
    assert "https" not in rendered
    assert set(summary) == {
        "campaign_id",
        "campaign_run_id",
        "finalized",
        "merged_artifact_digest",
        "operationally_validated",
        "persisted",
        "phase",
        "reason_codes",
        "receipt_digest",
    }


def _blocked_manifests() -> dict[str, dict[str, object]]:
    """Return one manifest per blocker class that MUST refuse finalization."""

    missing = _manifest()
    scenarios = _scenario_map(missing)
    del scenarios[OperationalHistoryScenario.WARM_REPLAY.value]
    missing["scenarios"] = scenarios
    undigested = _manifest()
    entries = _scenario_map(undigested)
    entries[OperationalHistoryScenario.WARM_REPLAY.value] = {
        "status": OperationalHistoryScenarioStatus.PASSED.value,
        "evidence_digests": [],
        "reason_codes": [],
    }
    undigested["scenarios"] = entries
    incomplete = _manifest()
    incomplete["deterministic_complete"] = False
    return {
        "scenario_failed": _degrade(OperationalHistoryScenarioStatus.FAILED),
        "scenario_unavailable": _degrade(OperationalHistoryScenarioStatus.UNAVAILABLE),
        "scenario_missing": missing,
        "digests_missing": undigested,
        "not_deterministic_complete": incomplete,
        "unmerged_phase": _manifest(phase=CampaignPhase.POST_RESTART.value),
    }


@pytest.mark.parametrize("blocker", sorted(_blocked_manifests()))
async def test_blocked_finalization_preserves_no_merged_artifact(
    tmp_path: Path, blocker: str
) -> None:
    """Final merged preservation MUST be conditional on every scenario passing."""

    sink = _Sink()
    certifier = _certified()
    summary = await finalize_campaign(
        _blocked_manifests()[blocker],
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=sink,
        certify=certifier,
    )
    assert sink.calls == []
    assert sink.artifacts.blobs == {}
    assert sink.manifests.rows == {}
    assert sink.index.rows == {}
    assert certifier.calls == []
    assert not (tmp_path / "receipt.json").exists()
    assert summary["merged_artifact_digest"] is None
    assert summary["finalized"] is False
    assert summary["reason_codes"]


async def test_passing_evidence_preserves_the_merged_artifact_before_certifying(
    tmp_path: Path,
) -> None:
    """Only unblocked evidence reaches the sink, and it does so before the certifier."""

    sink = _Sink()
    certifier = _certified()
    summary = await finalize_campaign(
        _manifest(), _options(tmp_path), _env(), now=NOW, sink=sink, certify=certifier
    )
    assert sink.calls == [(CAMPAIGN_ID, CampaignPhase.MERGED)]
    assert sink.manifests.rows
    assert sink.index.rows
    assert certifier.calls
    assert summary["reason_codes"] == []
    assert summary["finalized"] is True
    digest = summary["merged_artifact_digest"]
    assert isinstance(digest, str) and digest.startswith("sha256:")


async def test_blocked_finalization_summary_stays_sanitized(tmp_path: Path) -> None:
    summary = await finalize_campaign(
        _degrade(OperationalHistoryScenarioStatus.FAILED),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=_Sink(),
        certify=_certified(),
    )
    assert_sanitized(summary)
    assert summary["merged_artifact_digest"] is None


# ----------------------------------------------------------------------------
# Canonical ontology release identity
# ----------------------------------------------------------------------------


def test_canonical_catalog_release_is_the_bound_identity() -> None:
    """The campaign binds the source-built catalog release, not a caller value."""

    resolution = resolve_release_digest(None, canonical=CATALOG_DIGEST)
    assert resolution.digest == CATALOG_DIGEST
    assert resolution.assertion == RELEASE_VERIFIED
    assert resolution.verified is True


def test_matching_assertion_is_verified_against_the_catalog() -> None:
    resolution = resolve_release_digest(CATALOG_DIGEST, canonical=CATALOG_DIGEST)
    assert resolution.assertion == RELEASE_VERIFIED
    assert resolution.supplied == CATALOG_DIGEST


def test_a_workflow_archive_digest_never_overrides_the_catalog_release() -> None:
    """An unrelated digest is graded as a conflict and is never bound."""

    resolution = resolve_release_digest(RELEASE_DIGEST, canonical=CATALOG_DIGEST)
    assert resolution.digest == CATALOG_DIGEST
    assert resolution.assertion == RELEASE_CONFLICTED
    assert resolution.verified is False


def test_an_unbuildable_catalog_leaves_the_release_unverified() -> None:
    resolution = resolve_release_digest(RELEASE_DIGEST, canonical=None)
    assert resolution.digest == RELEASE_DIGEST
    assert resolution.assertion == RELEASE_UNVERIFIED
    assert resolution.verified is False


def test_release_resolution_requires_some_resolvable_digest() -> None:
    with pytest.raises(ValueError, match="resolvable ontology release digest"):
        resolve_release_digest(None, canonical=None)


def test_malformed_assertion_is_rejected() -> None:
    with pytest.raises(ValueError, match="MUST be a sha256 digest"):
        resolve_release_digest("not-a-digest", canonical=CATALOG_DIGEST)


def test_shipped_catalog_release_is_resolvable_in_this_runtime() -> None:
    """The production helper path must work wherever the job image runs."""

    digest = canonical_ontology_release_digest()
    assert digest.startswith("sha256:")
    assert digest == canonical_ontology_release_digest()


def test_options_bind_the_catalog_release_over_a_conflicting_workflow_value(
    tmp_path: Path,
) -> None:
    args = build_parser().parse_args(
        [
            "--phase",
            "before-restart",
            "--output",
            str(tmp_path / "before.json"),
            "--ontology-release-digest",
            RELEASE_DIGEST,
        ]
    )
    options = options_from_args(
        args, _env(), release=resolve_release_digest(RELEASE_DIGEST, canonical=CATALOG_DIGEST)
    )
    assert options.ontology_release_digest == CATALOG_DIGEST
    assert options.release_assertion == RELEASE_CONFLICTED


def test_options_do_not_require_a_supplied_release_digest(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["--phase", "before-restart", "--output", str(tmp_path / "before.json")]
    )
    environ = _env(FDAI_ONTOLOGY_RELEASE_DIGEST="")
    options = options_from_args(
        args, environ, release=resolve_release_digest(None, canonical=CATALOG_DIGEST)
    )
    assert options.ontology_release_digest == CATALOG_DIGEST
    assert options.release_assertion == RELEASE_VERIFIED


@pytest.mark.parametrize(
    ("assertion", "reason"),
    [
        (RELEASE_CONFLICTED, "ontology_release_digest_conflicted"),
        (RELEASE_UNVERIFIED, "ontology_release_digest_unverified"),
    ],
)
async def test_unverified_release_identity_never_certifies(
    tmp_path: Path, assertion: str, reason: str
) -> None:
    sink = _Sink()
    certifier = _certified()
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path, release_assertion=assertion),
        _env(),
        now=NOW,
        sink=sink,
        certify=certifier,
        projection=_Projection(),
    )
    assert summary["finalized"] is False
    assert reason in summary["reason_codes"]  # type: ignore[operator]
    assert certifier.calls == []
    assert sink.calls == []
    assert summary["merged_artifact_digest"] is None
    assert not (tmp_path / "receipt.json").exists()


async def test_a_contradicting_projection_record_never_certifies(tmp_path: Path) -> None:
    """A deployed projection bound to another release refuses the receipt."""

    sink = _Sink()
    certifier = _certified()
    projection = _Projection("sha256:" + "7" * 64)
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=sink,
        certify=certifier,
        projection=projection,
    )
    assert projection.keys == [INVENTORY_ONTOLOGY_MANIFEST_KEY]
    assert summary["reason_codes"] == ["ontology_release_projection_conflicted"]
    assert certifier.calls == []
    assert sink.calls == []


@pytest.mark.parametrize(
    "projection",
    [_Projection(record=False), _Projection(None), _UnreadableProjection()],
)
async def test_an_absent_projection_record_does_not_block_a_verified_release(
    tmp_path: Path, projection: object
) -> None:
    """Nothing to compare is unavailable, not agreement and not a refusal."""

    certifier = _certified()
    summary = await finalize_campaign(
        _manifest(),
        _options(tmp_path),
        _env(),
        now=NOW,
        sink=_Sink(),
        certify=certifier,
        projection=cast(Any, projection),
    )
    assert summary["finalized"] is True
    assert certifier.calls != []


def test_projection_state_never_reads_agreement_from_absence() -> None:
    assert projection_state(CATALOG_DIGEST, None) == PROJECTION_UNAVAILABLE
    assert projection_state(CATALOG_DIGEST, CATALOG_DIGEST) == PROJECTION_MATCHED
    assert projection_state(CATALOG_DIGEST, RELEASE_DIGEST) == PROJECTION_CONFLICTED
    assert release_blockers(RELEASE_VERIFIED, PROJECTION_UNAVAILABLE) == ()
